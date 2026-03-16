/**
 * Hook for pages to show red notification dots on specific elements.
 *
 * Usage:
 *   const { hasNotif, markRead } = useNotifDots('quality_done');
 *   // hasNotif('Condition') → true/false
 *   // markRead('Condition') → marks read + removes dot + refreshes sidebar badge
 *
 * Automatically refreshes when:
 * - Component mounts
 * - 'opal:badges-refresh' event fires (after sidebar poll or other page marks read)
 * - Window regains focus (user switches tabs)
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { notificationsApi } from '../api/client';

export function useNotifDots(notifType: string) {
  const [unreadItems, setUnreadItems] = useState<Set<string>>(new Set());
  const fetchingRef = useRef(false);

  const refresh = useCallback(() => {
    if (fetchingRef.current) return;
    fetchingRef.current = true;
    notificationsApi.items(notifType)
      .then(res => {
        const items = res.data.items[notifType] || [];
        setUnreadItems(new Set(items.map(i => i.item_id)));
      })
      .catch(() => {})
      .finally(() => { fetchingRef.current = false; });
  }, [notifType]);

  // Initial fetch + periodic refresh via events
  useEffect(() => {
    refresh();

    // Refresh when sidebar badges update or after markRead
    const onBadgeRefresh = () => refresh();
    window.addEventListener('opal:badges-refresh', onBadgeRefresh);

    // Refresh when tab regains focus
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);

    // Real-time: refresh when a WS notification of this type arrives
    const onWsNotif = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail && detail.type === notifType) refresh();
    };
    window.addEventListener('opal:notification', onWsNotif);

    // No polling — WS handles real-time push
    return () => {
      window.removeEventListener('opal:badges-refresh', onBadgeRefresh);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('opal:notification', onWsNotif);
    };
  }, [refresh]);

  const hasNotif = useCallback(
    (itemId: string) => unreadItems.has(itemId),
    [unreadItems]
  );

  const markRead = useCallback(
    (itemId: string) => {
      if (!unreadItems.has(itemId)) return;
      notificationsApi.markItemRead(notifType, itemId).catch(() => {});
      setUnreadItems(prev => {
        const next = new Set(prev);
        next.delete(itemId);
        return next;
      });
      // Tell the sidebar to refresh badge counts
      window.dispatchEvent(new Event('opal:badges-refresh'));
    },
    [notifType, unreadItems]
  );

  // Stable reference — safe to use in useEffect deps without re-triggering loops
  const markAllReadForType = useCallback(() => {
    notificationsApi.markAllRead(notifType).catch(() => {});
    setUnreadItems(new Set());
    window.dispatchEvent(new Event('opal:badges-refresh'));
  }, [notifType]);

  // Check if any unread item exists except the given ones
  const hasAnyNotifExcept = useCallback(
    (...excludeIds: string[]) => {
      const excl = new Set(excludeIds);
      for (const id of unreadItems) {
        if (!excl.has(id)) return true;
      }
      return false;
    },
    [unreadItems]
  );

  // Mark all items as read except the given ones (marks each individually)
  const markAllReadExcept = useCallback(
    (...excludeIds: string[]) => {
      const excl = new Set(excludeIds);
      const toMark = [...unreadItems].filter(id => !excl.has(id));
      if (toMark.length === 0) return;
      for (const id of toMark) {
        notificationsApi.markItemRead(notifType, id).catch(() => {});
      }
      setUnreadItems(prev => {
        const next = new Set(prev);
        for (const id of toMark) next.delete(id);
        return next;
      });
      window.dispatchEvent(new Event('opal:badges-refresh'));
    },
    [notifType, unreadItems]
  );

  const count = unreadItems.size;

  return { hasNotif, markRead, markAllReadForType, hasAnyNotifExcept, markAllReadExcept, count, unreadItems, refresh };
}
