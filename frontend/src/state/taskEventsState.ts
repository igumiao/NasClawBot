import { useCallback, useEffect, useRef, useState } from "react";
import { tasksApi } from "../api/tasksApi";
import type { TaskEventSummary } from "../types/api";

type UseTaskEventsResult = {
  events: TaskEventSummary[];
  acknowledge: (eventId: string) => Promise<void>;
  acknowledgeAll: () => Promise<void>;
  loading: boolean;
  error: string | null;
};

const POLL_INTERVAL_MS = 15_000;

/**
 * Polls GET /task-events every 15s for unacknowledged events scoped to the
 * given conversation session.  Stops polling on unmount and prevents
 * overlapping requests.
 *
 * When `sessionId` is `null` the hook returns empty state without polling.
 */
export function useTaskEvents(sessionId: string | null): UseTaskEventsResult {
  const [events, setEvents] = useState<TaskEventSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);

  const fetchEvents = useCallback(async () => {
    if (!sessionId || inFlightRef.current) return;
    inFlightRef.current = true;
    setLoading(true);
    try {
      const response = await tasksApi.listTaskEvents(
        { source_session_id: sessionId, acknowledged: false, limit: 50 },
      );
      if (mountedRef.current) {
        setEvents(Array.isArray(response.events) ? response.events : []);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : "获取任务事件失败");
      }
    } finally {
      inFlightRef.current = false;
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [sessionId]);

  const acknowledge = useCallback(async (eventId: string) => {
    try {
      await tasksApi.acknowledgeEvent(eventId);
      setEvents((prev) => prev.filter((e) => e.event_id !== eventId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "确认事件失败");
    }
  }, []);

  const acknowledgeAll = useCallback(async () => {
    const ids = events.map((e) => e.event_id);
    for (const eventId of ids) {
      try {
        await tasksApi.acknowledgeEvent(eventId);
      } catch {
        // Continue acknowledging remaining events even if one fails.
      }
    }
    setEvents([]);
  }, [events]);

  // Start/stop polling based on session changes.
  useEffect(() => {
    mountedRef.current = true;

    // Immediate fetch when session changes.
    if (sessionId) {
      fetchEvents();
    } else {
      setEvents([]);
      setError(null);
    }

    return () => {
      mountedRef.current = false;
      if (pollTimerRef.current !== null) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [sessionId, fetchEvents]);

  // Schedule periodic polling.
  useEffect(() => {
    if (!sessionId) return;

    const scheduleNext = () => {
      pollTimerRef.current = setTimeout(async () => {
        await fetchEvents();
        if (mountedRef.current) {
          scheduleNext();
        }
      }, POLL_INTERVAL_MS);
    };

    scheduleNext();

    return () => {
      if (pollTimerRef.current !== null) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [sessionId, fetchEvents]);

  return { events, acknowledge, acknowledgeAll, loading, error };
}
