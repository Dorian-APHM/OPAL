/**
 * Notification Center — slide-out drawer showing all notifications.
 *
 * Features:
 * - Real-time updates via WebSocket (opal:notification event)
 * - Filter by type (all, unread)
 * - Mark individual / all as read
 * - Delete read notifications
 * - Click to navigate to related page
 * - Time-ago display
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bell, Check, CheckCheck, Trash2, X,
  LayoutDashboard, Users, GitCompareArrows, HardDrive,
  Database, Shield, UserPlus, UserMinus, Share2,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { notificationsApi, type NotificationItem } from '../api/client';
import { Drawer } from './ui/Drawer';

interface NotificationCenterProps {
  open: boolean;
  onClose: () => void;
}

const TYPE_ICONS: Record<string, typeof Bell> = {
  quality_done: LayoutDashboard,
  cohort_shared: Share2,
  cohort_deleted: Users,
  cohort_updated: Users,
  mapping_review: GitCompareArrows,
  mapping_applied: GitCompareArrows,
  extraction_done: HardDrive,
  access_request: Shield,
  access_granted: UserPlus,
  access_revoked: UserMinus,
  cdm_created: Database,
  cdm_updated: Database,
  cdm_deleted: Database,
  group_added: Users,
  group_removed: UserMinus,
};

const TYPE_COLORS: Record<string, string> = {
  quality_done: 'text-emerald-400',
  cohort_shared: 'text-blue-400',
  cohort_deleted: 'text-red-400',
  cohort_updated: 'text-amber-400',
  mapping_review: 'text-purple-400',
  mapping_applied: 'text-purple-400',
  extraction_done: 'text-teal-400',
  access_request: 'text-amber-400',
  access_granted: 'text-emerald-400',
  access_revoked: 'text-red-400',
  cdm_created: 'text-emerald-400',
  cdm_updated: 'text-amber-400',
  cdm_deleted: 'text-red-400',
  group_added: 'text-blue-400',
  group_removed: 'text-red-400',
};

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '';
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.max(0, now - then);
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;
  return `${Math.floor(days / 30)}mo`;
}

export default function NotificationCenter({ open, onClose }: NotificationCenterProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);

  const fetchNotifications = useCallback(async () => {
    if (!open) return;
    setLoading(true);
    try {
      const res = await notificationsApi.list(filter === 'unread', 100);
      if (mountedRef.current) {
        setNotifications(res.data.notifications);
      }
    } catch {
      // silent
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [open, filter]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Fetch when opened or filter changes
  useEffect(() => {
    fetchNotifications();
  }, [fetchNotifications]);

  // Listen for real-time notifications
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as NotificationItem;
      if (detail && mountedRef.current) {
        setNotifications(prev => [detail, ...prev]);
      }
    };
    window.addEventListener('opal:notification', handler);
    return () => window.removeEventListener('opal:notification', handler);
  }, []);

  const markRead = async (id: number) => {
    await notificationsApi.markRead(id).catch(() => {});
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
    window.dispatchEvent(new Event('opal:badges-refresh'));
  };

  const markAllRead = async () => {
    await notificationsApi.markAllRead().catch(() => {});
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    window.dispatchEvent(new Event('opal:badges-refresh'));
  };

  const deleteNotif = async (id: number) => {
    await notificationsApi.deleteNotif(id).catch(() => {});
    setNotifications(prev => prev.filter(n => n.id !== id));
    window.dispatchEvent(new Event('opal:badges-refresh'));
  };

  const deleteAllRead = async () => {
    await notificationsApi.deleteAllRead().catch(() => {});
    setNotifications(prev => prev.filter(n => !n.read));
    window.dispatchEvent(new Event('opal:badges-refresh'));
  };

  const handleClick = (notif: NotificationItem) => {
    if (!notif.read) markRead(notif.id);
    if (notif.link) {
      navigate(notif.link);
      onClose();
    }
  };

  const unreadCount = notifications.filter(n => !n.read).length;
  const readCount = notifications.filter(n => n.read).length;

  return (
    <Drawer open={open} onClose={onClose} title={
      <div className="flex items-center gap-2">
        <Bell className="h-5 w-5 text-emerald-accent" />
        <span>Notifications</span>
        {unreadCount > 0 && (
          <span className="ml-1 px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 text-xs font-semibold">
            {unreadCount}
          </span>
        )}
      </div>
    } width="max-w-sm">
      {/* Actions bar */}
      <div className="flex items-center gap-2 mb-4 -mt-2">
        <button
          onClick={() => setFilter('all')}
          className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer border-none ${
            filter === 'all' ? 'bg-emerald-accent/15 text-emerald-accent' : 'bg-surface-light text-text-dim hover:text-text-muted'
          }`}
        >
          All
        </button>
        <button
          onClick={() => setFilter('unread')}
          className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer border-none ${
            filter === 'unread' ? 'bg-emerald-accent/15 text-emerald-accent' : 'bg-surface-light text-text-dim hover:text-text-muted'
          }`}
        >
          Unread ({unreadCount})
        </button>
        <div className="flex-1" />
        {unreadCount > 0 && (
          <button
            onClick={markAllRead}
            title="Mark all as read"
            className="p-1.5 rounded-lg text-text-dim hover:text-emerald-accent hover:bg-emerald-accent/10 transition-colors cursor-pointer bg-transparent border-none"
          >
            <CheckCheck className="h-4 w-4" />
          </button>
        )}
        {readCount > 0 && (
          <button
            onClick={deleteAllRead}
            title="Delete all read"
            className="p-1.5 rounded-lg text-text-dim hover:text-red-400 hover:bg-red-400/10 transition-colors cursor-pointer bg-transparent border-none"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Notification list */}
      {loading && notifications.length === 0 ? (
        <div className="text-center text-text-dim text-sm py-8">Loading...</div>
      ) : notifications.length === 0 ? (
        <div className="text-center text-text-dim text-sm py-8">
          <Bell className="h-8 w-8 mx-auto mb-2 opacity-30" />
          <p>No notifications</p>
        </div>
      ) : (
        <div className="space-y-1">
          {notifications.map(notif => {
            const Icon = TYPE_ICONS[notif.type] || Bell;
            const colorClass = TYPE_COLORS[notif.type] || 'text-text-dim';
            return (
              <div
                key={notif.id}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleClick(notif); } }}
                className={`group relative flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-all duration-150 ${
                  notif.read
                    ? 'bg-transparent hover:bg-surface-light/50 opacity-60'
                    : 'bg-emerald-accent/5 hover:bg-emerald-accent/10 border-l-2 border-emerald-accent'
                }`}
                onClick={() => handleClick(notif)}
              >
                <div className={`mt-0.5 shrink-0 ${colorClass}`}>
                  <Icon className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <p className={`text-sm leading-tight ${notif.read ? 'text-text-muted' : 'text-text-bright font-medium'}`}>
                      {notif.title}
                    </p>
                    <span className="text-[10px] text-text-dim shrink-0 mt-0.5">{timeAgo(notif.created_at)}</span>
                  </div>
                  {notif.message && (
                    <p className="text-xs text-text-dim mt-0.5 line-clamp-2">{notif.message}</p>
                  )}
                </div>
                {/* Quick actions on hover */}
                <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity flex gap-1">
                  {!notif.read && (
                    <button
                      onClick={(e) => { e.stopPropagation(); markRead(notif.id); }}
                      title="Mark as read"
                      aria-label="Mark as read"
                      className="p-1 rounded bg-surface hover:bg-emerald-accent/20 text-text-dim hover:text-emerald-accent cursor-pointer border-none transition-colors"
                    >
                      <Check className="h-3 w-3" />
                    </button>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); deleteNotif(notif.id); }}
                    title="Delete"
                    aria-label="Delete notification"
                    className="p-1 rounded bg-surface hover:bg-red-400/20 text-text-dim hover:text-red-400 cursor-pointer border-none transition-colors"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Drawer>
  );
}
