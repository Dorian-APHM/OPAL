import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Card, Button, Input, Tabs, Tag, Badge, Spinner,
} from '../components/ui';
import type { TabItem } from '../components/ui';
import { useToast } from '../components/ui';
import {
  Play, StopCircle, Folder, File, Download, Home, RefreshCw,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ohdsiApi, cdmApi, authDownload } from '../api/client';

interface Props {
  selectedCdm: string | null;
}

type ServiceStatus = 'idle' | 'running' | 'done' | 'error';

interface ServiceState {
  status: ServiceStatus;
  logs: string[];
  cdm_name?: string;
}

interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
}

const SERVICES = [
  { key: 'achilles', label: 'Achilles' },
  { key: 'dqd', label: 'Data Quality Dashboard' },
  { key: 'achilles-export', label: 'Achilles Export' },
  { key: 'cdmonboarding', label: 'CDM Onboarding' },
];

const STATUS_BADGE: Record<ServiceStatus, 'default' | 'processing' | 'success' | 'error'> = {
  idle: 'default',
  running: 'processing',
  done: 'success',
  error: 'error',
};

const STATUS_TAG_COLOR: Record<ServiceStatus, 'orange' | 'green' | 'red' | 'default'> = {
  idle: 'default',
  running: 'orange',
  done: 'green',
  error: 'red',
};

function formatSize(bytes: number | null): string {
  if (bytes === null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function OhdsiPage({ selectedCdm }: Props) {
  const { t } = useTranslation();
  const toast = useToast();

  // Config form
  const [resultsSchema, setResultsSchema] = useState('omop_cdm');
  const [vocabSchema, setVocabSchema] = useState('omop_cdm');
  const [cdmVersion, setCdmVersion] = useState('5.4');
  const [cdmSourceName, setCdmSourceName] = useState('');

  // Services state
  const [services, setServices] = useState<Record<string, ServiceState>>({});
  const [activeLogTab, setActiveLogTab] = useState<string>('achilles');
  const eventSourcesRef = useRef<Record<string, EventSource>>({});
  const logOffsetRef = useRef<Record<string, number>>({});
  const logContainerRef = useRef<HTMLDivElement>(null);
  const prevLogCountRef = useRef<Record<string, number>>({});

  // File browser
  const [currentPath, setCurrentPath] = useState('');
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);

  // OHDSI feature flag (server-side OHDSI_MODE). null = loading.
  const [enabled, setEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    ohdsiApi.config()
      .then((res) => setEnabled(!!res.data.enabled))
      .catch(() => setEnabled(false));
  }, []);

  // Pre-fill config from CDM
  useEffect(() => {
    if (!selectedCdm) return;
    cdmApi.getSettings(selectedCdm).then((res) => {
      const cats = res.data.schema_categories || {};
      if (res.data.omop_schema) {
        // Results use the clinical schema; vocabulary uses its category schema when set.
        setResultsSchema(cats.clinical || res.data.omop_schema);
        setVocabSchema(cats.vocabulary || res.data.omop_schema);
      }
    }).catch(() => toast.error('Failed to load CDM settings'));
    setCdmSourceName(selectedCdm);
  }, [selectedCdm]);

  // Poll status
  useEffect(() => {
    if (enabled !== true) return;
    const poll = setInterval(() => {
      ohdsiApi.status().then((res) => {
        setServices((prev) => {
          const next = { ...prev };
          for (const [svc, info] of Object.entries(res.data)) {
            if (!next[svc]) next[svc] = { status: 'idle', logs: [] };
            next[svc] = { ...next[svc], status: info.status as ServiceStatus, cdm_name: (info as any).cdm_name || '' };
          }
          return next;
        });
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(poll);
  }, [enabled]);

  // Load files
  const loadFiles = useCallback((path: string) => {
    setLoadingFiles(true);
    ohdsiApi.files(path).then((res) => {
      setFiles(res.data as FileEntry[]);
      setCurrentPath(path);
    }).catch(() => setFiles([])).finally(() => setLoadingFiles(false));
  }, []);

  // Auto-navigate file browser to CDM-specific folder
  useEffect(() => {
    if (selectedCdm) {
      loadFiles(selectedCdm);
    } else {
      loadFiles('');
    }
  }, [loadFiles, selectedCdm]);

  // SSE log streaming with auto-reconnect and offset tracking
  const startSSE = useCallback(async (service: string) => {
    // Close existing
    if (eventSourcesRef.current[service]) {
      eventSourcesRef.current[service].close();
    }

    const offset = logOffsetRef.current[service] || 0;
    const url = await ohdsiApi.logsUrl(service, offset);
    const es = new EventSource(url);
    eventSourcesRef.current[service] = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.lines && data.lines.length > 0) {
          setServices((prev) => {
            const svc = prev[service] || { status: 'idle', logs: [] };
            return {
              ...prev,
              [service]: {
                status: data.status as ServiceStatus,
                logs: [...svc.logs, ...data.lines],
              },
            };
          });
        } else if (data.status) {
          setServices((prev) => ({
            ...prev,
            [service]: {
              ...(prev[service] || { status: 'idle', logs: [] }),
              status: data.status as ServiceStatus,
            },
          }));
        }
        if (data.offset !== undefined) {
          logOffsetRef.current[service] = data.offset;
        }
        if (data.status === 'done' || data.status === 'error') {
          es.close();
          delete eventSourcesRef.current[service];
          loadFiles(currentPath);
        }
      } catch { /* ignore */ }
    };

    es.onerror = () => {
      es.close();
      delete eventSourcesRef.current[service];
      // Auto-reconnect after 2s if still running
      setTimeout(() => {
        setServices((prev) => {
          const svc = prev[service];
          if (svc && svc.status === 'running') {
            startSSE(service);
          }
          return prev;
        });
      }, 2000);
    };
  }, [currentPath, loadFiles]);

  // On mount: recover logs from backend for any non-idle service
  const recoveredRef = useRef(false);
  useEffect(() => {
    if (enabled !== true || recoveredRef.current) return;
    recoveredRef.current = true;
    SERVICES.forEach(({ key }) => {
      ohdsiApi.logsHistory(key).then((res) => {
        const { status, logs, offset } = res.data;
        if (status === 'idle' && logs.length === 0) return;
        logOffsetRef.current[key] = offset;
        setServices((prev) => ({
          ...prev,
          [key]: { status: status as ServiceStatus, logs },
        }));
        // If still running, reconnect SSE to stream new logs
        if (status === 'running') {
          startSSE(key);
        }
      }).catch(() => toast.error(`Failed to recover logs for ${key}`));
    });
    return () => {
      // Cleanup SSE connections on unmount
      Object.values(eventSourcesRef.current).forEach((es) => es.close());
      eventSourcesRef.current = {};
    };
  }, [startSSE, enabled]);

  // Auto-scroll the log box (NOT the page) when new lines arrive — and only if the
  // user is already near the bottom, so scrolling up to reach Stop isn't fought.
  useEffect(() => {
    const key = activeLogTab;
    const currentCount = services[key]?.logs?.length || 0;
    const prevCount = prevLogCountRef.current[key] || 0;
    const el = logContainerRef.current;
    if (currentCount > prevCount && el) {
      const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 50;
      if (nearBottom) el.scrollTop = el.scrollHeight;
    }
    prevLogCountRef.current[key] = currentCount;
  }, [services, activeLogTab]);

  const handleRun = async (service: string) => {
    if (!selectedCdm) {
      toast.warning(t('ohdsi.select_cdm'));
      return;
    }

    try {
      // Clear previous logs and reset offset
      logOffsetRef.current[service] = 0;
      setServices((prev) => ({
        ...prev,
        [service]: { status: 'running', logs: [] },
      }));
      setActiveLogTab(service);

      await ohdsiApi.run(service, {
        cdm_name: selectedCdm,
        results_schema: resultsSchema,
        vocabulary_schema: vocabSchema,
        cdm_version: cdmVersion,
        cdm_source_name: cdmSourceName || selectedCdm,
      });

      // Start SSE log streaming
      startSSE(service);
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message;
      toast.error(detail);
      setServices((prev) => ({
        ...prev,
        [service]: { status: 'error', logs: [detail] },
      }));
    }
  };

  const handleStop = async (service: string) => {
    try {
      await ohdsiApi.stop(service);
      toast.success(t('ohdsi.stopped'));
    } catch (err: any) {
      toast.error(err.response?.data?.detail || err.message);
    }
  };

  const getStatus = (service: string): ServiceStatus =>
    services[service]?.status || 'idle';

  const getLogs = (service: string): string[] =>
    services[service]?.logs || [];

  // Breadcrumb parts
  const pathParts = currentPath ? currentPath.split('/') : [];

  if (enabled === false) {
    return (
      <div className="py-10 text-center">
        <h4 className="text-lg font-semibold text-text-dim">
          {t('ohdsi.disabled', 'OHDSI tools are disabled on this server (OHDSI_MODE=off).')}
        </h4>
      </div>
    );
  }

  if (!selectedCdm) {
    return (
      <div className="py-10 text-center">
        <h4 className="text-lg font-semibold text-text-dim">{t('ohdsi.select_cdm')}</h4>
      </div>
    );
  }

  const logTabItems: TabItem[] = SERVICES.map(({ key, label }) => {
    const status = getStatus(key);
    return {
      key,
      label: (
        <span className="inline-flex items-center gap-1.5">
          <Badge status={STATUS_BADGE[status]} />
          {label}
        </span>
      ),
      children: (
        <div ref={logContainerRef} className="h-[300px] overflow-auto bg-deep-base text-text-bright font-mono text-xs p-3 rounded mb-3">
          {getLogs(key).length === 0 ? (
            <span className="text-text-dim">{t('ohdsi.no_logs')}</span>
          ) : (
            getLogs(key).map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                {line}
              </div>
            ))
          )}
        </div>
      ),
    };
  });

  return (
    <div>
      <h3 className="text-xl font-semibold text-text-bright mb-4">{t('ohdsi.title')}</h3>

      <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,2.5fr)] gap-4">
        {/* Configuration panel */}
        <Card title={t('ohdsi.configuration')} size="small" className="mb-4 md:mb-0">
          <div className="flex flex-col gap-3">
            <div>
              <span className="text-text-dim text-xs block mb-1">{t('ohdsi.results_schema')} <span className="text-red-400">*</span></span>
              <Input value={resultsSchema} onChange={(e) => setResultsSchema(e.target.value)} />
            </div>
            <div>
              <span className="text-text-dim text-xs block mb-1">{t('ohdsi.vocab_schema')} <span className="text-red-400">*</span></span>
              <Input value={vocabSchema} onChange={(e) => setVocabSchema(e.target.value)} />
            </div>
            <div>
              <span className="text-text-dim text-xs block mb-1">{t('ohdsi.cdm_version')} <span className="text-red-400">*</span></span>
              <Input value={cdmVersion} onChange={(e) => setCdmVersion(e.target.value)} />
            </div>
            <div>
              <span className="text-text-dim text-xs block mb-1">{t('ohdsi.source_name')} <span className="text-red-400">*</span></span>
              <Input value={cdmSourceName} onChange={(e) => setCdmSourceName(e.target.value)} />
            </div>
          </div>
        </Card>

        {/* Services grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
          {SERVICES.map(({ key, label }) => {
            const status = getStatus(key);
            const svcCdm = services[key]?.cdm_name;
            const isRunning = status === 'running';
            return (
              <Card key={key} size="small" className="text-center">
                <div className="flex flex-col items-center gap-2">
                  <Badge status={STATUS_BADGE[status]} />
                  <div className="font-semibold text-text-bright text-[13px]">{label}</div>
                  {svcCdm && status !== 'idle' && (
                    <div className="text-xs text-text-dim truncate max-w-full" title={svcCdm}>
                      CDM: {svcCdm}
                    </div>
                  )}
                  <Tag color={STATUS_TAG_COLOR[status]}>
                    {t(`ohdsi.status_${status}`)}
                  </Tag>
                  <div>
                    {isRunning ? (
                      <Button
                        variant="danger"
                        size="small"
                        icon={<StopCircle className="h-3.5 w-3.5" />}
                        onClick={() => handleStop(key)}
                      >
                        Stop
                      </Button>
                    ) : (
                      <Button
                        variant="primary"
                        size="small"
                        icon={<Play className="h-3.5 w-3.5" />}
                        onClick={() => handleRun(key)}
                      >
                        {t('ohdsi.run')}
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Logs section */}
      <Card
        title={t('ohdsi.logs')}
        size="small"
        className="mt-4"
      >
        <Tabs
          items={logTabItems}
          activeKey={activeLogTab}
          onChange={setActiveLogTab}
        />
      </Card>

      {/* File browser */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <span>{t('ohdsi.results')}</span>
            <Button
              size="small"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={() => loadFiles(currentPath)}
            />
          </div>
        }
        size="small"
        className="mt-4"
      >
        {/* Breadcrumb */}
        <nav className="flex items-center gap-1 text-sm mb-3 flex-wrap">
          <a
            className="inline-flex items-center gap-1 text-emerald-accent hover:underline cursor-pointer"
            onClick={() => loadFiles('')}
          >
            <Home className="h-3.5 w-3.5" /> output
          </a>
          {pathParts.map((part, idx) => {
            const subPath = pathParts.slice(0, idx + 1).join('/');
            return (
              <span key={subPath} className="inline-flex items-center gap-1">
                <span className="text-text-dim">/</span>
                <a
                  className="text-emerald-accent hover:underline cursor-pointer"
                  onClick={() => loadFiles(subPath)}
                >
                  {part}
                </a>
              </span>
            );
          })}
        </nav>

        {/* File list */}
        {loadingFiles ? (
          <div className="text-center py-6">
            <Spinner />
            <p className="text-sm text-text-muted mt-2">{t('ohdsi.loading_files', 'Loading files...')}</p>
          </div>
        ) : files.length === 0 ? (
          <div className="text-center py-6 text-text-dim text-sm">{t('ohdsi.no_files')}</div>
        ) : (
          <ul className="divide-y divide-glass-border">
            {files.map((file) => (
              <li
                key={file.path}
                className="flex items-center justify-between py-2 px-2 hover:bg-surface-light/50 rounded cursor-pointer transition-colors"
                onClick={() => { if (file.is_dir) loadFiles(file.path); }}
              >
                <div className="flex items-center gap-3 min-w-0">
                  {file.is_dir ? (
                    <Folder className="h-4 w-4 text-yellow-400 shrink-0" />
                  ) : (
                    <File className="h-4 w-4 text-text-dim shrink-0" />
                  )}
                  <div className="min-w-0">
                    <div className="text-sm text-text-bright truncate">{file.name}</div>
                    {!file.is_dir && file.size !== null && (
                      <div className="text-xs text-text-dim">{formatSize(file.size)}</div>
                    )}
                  </div>
                </div>
                {!file.is_dir && (
                  <a
                    className="text-text-dim hover:text-emerald-accent cursor-pointer shrink-0 ml-2"
                    onClick={(e) => { e.stopPropagation(); authDownload(ohdsiApi.fileUrl(file.path)); }}
                  >
                    <Download className="h-4 w-4" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
