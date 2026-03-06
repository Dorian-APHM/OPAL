import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Card,
  Button,
  Input,
  Row,
  Col,
  Badge,
  Tabs,
  Typography,
  Space,
  message,
  Breadcrumb,
  List,
  Tag,
} from 'antd';
import {
  PlayCircleOutlined,
  StopOutlined,
  FolderOutlined,
  FileOutlined,
  DownloadOutlined,
  HomeOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { ohdsiApi, cdmApi, authDownload } from '../api/client';

const { Text, Title } = Typography;

interface Props {
  selectedCdm: string | null;
}

type ServiceStatus = 'idle' | 'running' | 'done' | 'error';

interface ServiceState {
  status: ServiceStatus;
  logs: string[];
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

const STATUS_COLORS: Record<ServiceStatus, string> = {
  idle: 'default',
  running: 'processing',
  done: 'success',
  error: 'error',
};

function formatSize(bytes: number | null): string {
  if (bytes === null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function OhdsiPage({ selectedCdm }: Props) {
  const { t } = useTranslation();

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
  const logEndRef = useRef<HTMLDivElement>(null);

  // File browser
  const [currentPath, setCurrentPath] = useState('');
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);

  // Pre-fill config from CDM
  useEffect(() => {
    if (!selectedCdm) return;
    cdmApi.getSettings(selectedCdm).then((res) => {
      if (res.data.omop_schema) {
        setResultsSchema(res.data.omop_schema);
        setVocabSchema(res.data.omop_schema);
      }
    }).catch(() => {});
    setCdmSourceName(selectedCdm);
  }, [selectedCdm]);

  // Poll status
  useEffect(() => {
    const poll = setInterval(() => {
      ohdsiApi.status().then((res) => {
        setServices((prev) => {
          const next = { ...prev };
          for (const [svc, info] of Object.entries(res.data)) {
            if (!next[svc]) next[svc] = { status: 'idle', logs: [] };
            next[svc] = { ...next[svc], status: info.status as ServiceStatus };
          }
          return next;
        });
      }).catch(() => {});
    }, 3000);
    return () => clearInterval(poll);
  }, []);

  // Load files
  const loadFiles = useCallback((path: string) => {
    setLoadingFiles(true);
    ohdsiApi.files(path).then((res) => {
      setFiles(res.data as FileEntry[]);
      setCurrentPath(path);
    }).catch(() => setFiles([])).finally(() => setLoadingFiles(false));
  }, []);

  useEffect(() => {
    loadFiles('');
  }, [loadFiles]);

  // SSE log streaming with auto-reconnect and offset tracking
  const startSSE = useCallback((service: string) => {
    // Close existing
    if (eventSourcesRef.current[service]) {
      eventSourcesRef.current[service].close();
    }

    const offset = logOffsetRef.current[service] || 0;
    const es = new EventSource(ohdsiApi.logsUrl(service, offset));
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
    if (recoveredRef.current) return;
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
      }).catch(() => {});
    });
    return () => {
      // Cleanup SSE connections on unmount
      Object.values(eventSourcesRef.current).forEach((es) => es.close());
      eventSourcesRef.current = {};
    };
  }, [startSSE]);

  // Auto-scroll logs
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [services, activeLogTab]);

  const handleRun = async (service: string) => {
    if (!selectedCdm) {
      message.warning(t('ohdsi.select_cdm'));
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
      message.error(detail);
      setServices((prev) => ({
        ...prev,
        [service]: { status: 'error', logs: [detail] },
      }));
    }
  };

  const handleStop = async (service: string) => {
    try {
      await ohdsiApi.stop(service);
      message.success(t('ohdsi.stopped'));
    } catch (err: any) {
      message.error(err.response?.data?.detail || err.message);
    }
  };

  const getStatus = (service: string): ServiceStatus =>
    services[service]?.status || 'idle';

  const getLogs = (service: string): string[] =>
    services[service]?.logs || [];

  // Breadcrumb parts
  const pathParts = currentPath ? currentPath.split('/') : [];

  if (!selectedCdm) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Title level={4} type="secondary">{t('ohdsi.select_cdm')}</Title>
      </div>
    );
  }

  return (
    <div>
      <Title level={3} style={{ marginBottom: 16 }}>{t('ohdsi.title')}</Title>

      <Row gutter={16}>
        {/* Configuration panel */}
        <Col xs={24} md={8} lg={6}>
          <Card title={t('ohdsi.configuration')} size="small" style={{ marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size="small">
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('ohdsi.results_schema')}</Text>
                <Input size="small" value={resultsSchema} onChange={(e) => setResultsSchema(e.target.value)} />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('ohdsi.vocab_schema')}</Text>
                <Input size="small" value={vocabSchema} onChange={(e) => setVocabSchema(e.target.value)} />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('ohdsi.cdm_version')}</Text>
                <Input size="small" value={cdmVersion} onChange={(e) => setCdmVersion(e.target.value)} />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('ohdsi.source_name')}</Text>
                <Input size="small" value={cdmSourceName} onChange={(e) => setCdmSourceName(e.target.value)} />
              </div>
            </Space>
          </Card>
        </Col>

        {/* Services grid */}
        <Col xs={24} md={16} lg={18}>
          <Row gutter={[12, 12]}>
            {SERVICES.map(({ key, label }) => {
              const status = getStatus(key);
              const isRunning = status === 'running';
              return (
                <Col xs={12} sm={12} md={6} key={key}>
                  <Card
                    size="small"
                    style={{ textAlign: 'center' }}
                    styles={{ body: { padding: '16px 12px' } }}
                  >
                    <Badge status={STATUS_COLORS[status] as any} />
                    <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>{label}</div>
                    <Tag color={
                      status === 'running' ? 'orange' :
                      status === 'done' ? 'green' :
                      status === 'error' ? 'red' : 'default'
                    } style={{ marginBottom: 8 }}>
                      {t(`ohdsi.status_${status}`)}
                    </Tag>
                    <div>
                      {isRunning ? (
                        <Button
                          danger
                          size="small"
                          icon={<StopOutlined />}
                          onClick={() => handleStop(key)}
                        >
                          Stop
                        </Button>
                      ) : (
                        <Button
                          type="primary"
                          size="small"
                          icon={<PlayCircleOutlined />}
                          onClick={() => handleRun(key)}
                        >
                          {t('ohdsi.run')}
                        </Button>
                      )}
                    </div>
                  </Card>
                </Col>
              );
            })}
          </Row>
        </Col>
      </Row>

      {/* Logs section */}
      <Card
        title={t('ohdsi.logs')}
        size="small"
        style={{ marginTop: 16 }}
        styles={{ body: { padding: 0 } }}
      >
        <Tabs
          activeKey={activeLogTab}
          onChange={setActiveLogTab}
          size="small"
          style={{ padding: '0 12px' }}
          items={SERVICES.map(({ key, label }) => {
            const status = getStatus(key);
            return {
              key,
              label: (
                <span>
                  <Badge
                    status={STATUS_COLORS[status] as any}
                    style={{ marginRight: 4 }}
                  />
                  {label}
                </span>
              ),
              children: (
                <div
                  style={{
                    height: 300,
                    overflow: 'auto',
                    background: '#1e1e1e',
                    color: '#d4d4d4',
                    fontFamily: 'monospace',
                    fontSize: 12,
                    padding: 12,
                    borderRadius: 4,
                    marginBottom: 12,
                  }}
                >
                  {getLogs(key).length === 0 ? (
                    <Text type="secondary" style={{ color: '#666' }}>
                      {t('ohdsi.no_logs')}
                    </Text>
                  ) : (
                    getLogs(key).map((line, i) => (
                      <div key={i} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                        {line}
                      </div>
                    ))
                  )}
                  <div ref={logEndRef} />
                </div>
              ),
            };
          })}
        />
      </Card>

      {/* File browser */}
      <Card
        title={
          <Space>
            <span>{t('ohdsi.results')}</span>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => loadFiles(currentPath)}
            />
          </Space>
        }
        size="small"
        style={{ marginTop: 16 }}
      >
        <Breadcrumb style={{ marginBottom: 12 }}>
          <Breadcrumb.Item>
            <a onClick={() => loadFiles('')}>
              <HomeOutlined /> output
            </a>
          </Breadcrumb.Item>
          {pathParts.map((part, idx) => {
            const subPath = pathParts.slice(0, idx + 1).join('/');
            return (
              <Breadcrumb.Item key={subPath}>
                <a onClick={() => loadFiles(subPath)}>{part}</a>
              </Breadcrumb.Item>
            );
          })}
        </Breadcrumb>

        <List
          loading={loadingFiles}
          size="small"
          dataSource={files}
          locale={{ emptyText: t('ohdsi.no_files') }}
          renderItem={(file) => (
            <List.Item
              style={{ cursor: 'pointer', padding: '4px 8px' }}
              onClick={() => {
                if (file.is_dir) {
                  loadFiles(file.path);
                }
              }}
              actions={
                !file.is_dir
                  ? [
                      <a
                        onClick={(e) => { e.stopPropagation(); authDownload(ohdsiApi.fileUrl(file.path)); }}
                        style={{ cursor: 'pointer' }}
                      >
                        <DownloadOutlined />
                      </a>,
                    ]
                  : undefined
              }
            >
              <List.Item.Meta
                avatar={file.is_dir ? <FolderOutlined style={{ color: '#faad14' }} /> : <FileOutlined />}
                title={file.name}
                description={file.is_dir ? null : formatSize(file.size)}
              />
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
}
