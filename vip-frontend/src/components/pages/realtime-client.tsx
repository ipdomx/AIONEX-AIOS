"use client";

import {
  Camera,
  CameraOff,
  CircleStop,
  Copy,
  LoaderCircle,
  Mic,
  MicOff,
  MonitorUp,
  PhoneCall,
  PhoneOff,
  Radio,
  RefreshCw,
  ShieldCheck,
  Video,
} from "lucide-react";
import { Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusMessage } from "@/components/ui/status-message";
import { useAuth } from "@/hooks/use-auth";
import {
  closeRealtimeRoom,
  createRealtimeRoom,
  joinRealtimeRoom,
  leaveRealtimeRoom,
  listRealtimeRecordings,
  listRealtimeRooms,
  realtimeReadiness,
  requestRealtimeRecording,
  setRealtimeRecordingConsent,
  stopRealtimeRecording,
  type RealtimeReadiness,
  type RealtimeRecording,
  type RealtimeRoom,
} from "@/lib/realtime-api";

const activeRecordingStatuses = new Set(["awaiting_consent", "starting", "active", "ending"]);

function errorText(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

function requestId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export function RealtimeClient() {
  const t = useTranslations("realtime");
  const locale = useLocale();
  const router = useRouter();
  const { user, isAuthenticated, isLoading } = useAuth();
  const [readiness, setReadiness] = useState<RealtimeReadiness | null>(null);
  const [rooms, setRooms] = useState<RealtimeRoom[]>([]);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [recordings, setRecordings] = useState<RealtimeRecording[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [connected, setConnected] = useState(false);
  const [cameraEnabled, setCameraEnabled] = useState(false);
  const [micEnabled, setMicEnabled] = useState(false);
  const [screenEnabled, setScreenEnabled] = useState(false);
  const liveRoomRef = useRef<Room | null>(null);
  const mediaRootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) router.replace(`/${locale}/login`);
  }, [isAuthenticated, isLoading, locale, router]);

  const selectedRoom = useMemo(
    () => rooms.find((room) => room.id === selectedRoomId) || null,
    [rooms, selectedRoomId],
  );

  const loadRooms = useCallback(async () => {
    if (!isAuthenticated) return;
    const [ready, roomRows] = await Promise.all([realtimeReadiness(), listRealtimeRooms()]);
    setReadiness(ready);
    setRooms(roomRows);
    setSelectedRoomId((current) =>
      current && roomRows.some((room) => room.id === current) ? current : roomRows[0]?.id || null,
    );
  }, [isAuthenticated]);

  const loadRecordings = useCallback(async () => {
    if (!selectedRoomId || !isAuthenticated) {
      setRecordings([]);
      return;
    }
    setRecordings(await listRealtimeRecordings(selectedRoomId));
  }, [isAuthenticated, selectedRoomId]);

  useEffect(() => {
    if (!isAuthenticated) return;
    setBusy("load");
    setError("");
    void loadRooms()
      .catch((cause) => setError(errorText(cause, t("loadError"))))
      .finally(() => setBusy(null));
  }, [isAuthenticated, loadRooms, t]);

  useEffect(() => {
    void loadRecordings().catch((cause) => setError(errorText(cause, t("loadError"))));
  }, [loadRecordings, selectedRoomId, t]);

  useEffect(() => {
    if (!recordings.some((item) => activeRecordingStatuses.has(item.status))) return;
    const timer = window.setInterval(() => {
      void loadRecordings().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadRecordings, recordings]);

  const clearMedia = useCallback(() => {
    mediaRootRef.current?.replaceChildren();
  }, []);

  const attachTrack = useCallback((track: RemoteTrack) => {
    const element = track.attach();
    element.setAttribute("data-livekit-track", track.sid || "track");
    if (element instanceof HTMLVideoElement) {
      element.autoplay = true;
      element.playsInline = true;
      element.className = "aspect-video w-full rounded-2xl bg-black object-cover";
    } else if (element instanceof HTMLAudioElement) {
      element.autoplay = true;
      element.className = "hidden";
    }
    mediaRootRef.current?.appendChild(element);
  }, []);

  const detachTrack = useCallback((track: RemoteTrack) => {
    for (const element of track.detach()) element.remove();
  }, []);

  async function createRoom(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const roomKey = String(values.get("room_key") || "").trim();
    setBusy("create-room");
    setError("");
    setMessage("");
    try {
      const room = await createRealtimeRoom({
        room_key: roomKey,
        idempotency_key: requestId("room"),
        room_type: "meeting",
        media_mode: "audio_video",
        max_participants: 50,
        allow_screen_share: true,
      });
      setRooms((current) => [room, ...current.filter((item) => item.id !== room.id)]);
      setSelectedRoomId(room.id);
      form.reset();
      setMessage(t("roomCreated"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  async function join(room: RealtimeRoom) {
    if (liveRoomRef.current) await leave();
    setBusy(`join:${room.id}`);
    setError("");
    setMessage("");
    clearMedia();
    try {
      const joined = await joinRealtimeRoom(room.id, {
        idempotency_key: requestId("join"),
        can_publish: true,
        can_subscribe: true,
        can_screen_share: room.allow_screen_share,
      });
      const liveRoom = new Room({
        adaptiveStream: true,
        dynacast: true,
      });
      liveRoom.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        attachTrack(track);
      });
      liveRoom.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => detachTrack(track));
      liveRoom.on(RoomEvent.Disconnected, () => {
        setConnected(false);
        setCameraEnabled(false);
        setMicEnabled(false);
        setScreenEnabled(false);
        clearMedia();
      });
      await liveRoom.connect(joined.session.server_url, joined.session.token, {
        rtcConfig: { iceServers: joined.session.ice_servers },
      });
      liveRoomRef.current = liveRoom;
      setSelectedRoomId(room.id);
      setConnected(true);
      await liveRoom.localParticipant.setMicrophoneEnabled(true);
      setMicEnabled(true);
      await liveRoom.localParticipant.setCameraEnabled(true);
      setCameraEnabled(true);
      const localCamera = liveRoom.localParticipant.getTrackPublication(Track.Source.Camera)?.track;
      if (localCamera) {
        const element = localCamera.attach();
        if (element instanceof HTMLVideoElement) {
          element.muted = true;
          element.autoplay = true;
          element.playsInline = true;
          element.className = "aspect-video w-full rounded-2xl border border-electric-300/20 bg-black object-cover";
        }
        mediaRootRef.current?.prepend(element);
      }
      await Promise.all([loadRooms(), loadRecordings()]);
      setMessage(t("joined"));
    } catch (cause) {
      liveRoomRef.current?.disconnect();
      liveRoomRef.current = null;
      setConnected(false);
      clearMedia();
      setError(errorText(cause, t("joinError")));
    } finally {
      setBusy(null);
    }
  }

  async function leave() {
    const roomId = selectedRoomId;
    const liveRoom = liveRoomRef.current;
    liveRoomRef.current = null;
    liveRoom?.disconnect();
    clearMedia();
    setConnected(false);
    setCameraEnabled(false);
    setMicEnabled(false);
    setScreenEnabled(false);
    if (!roomId) return;
    try {
      await leaveRealtimeRoom(roomId);
      await loadRooms();
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    }
  }

  useEffect(() => () => {
    const room = liveRoomRef.current;
    liveRoomRef.current = null;
    room?.disconnect();
  }, []);

  async function toggleCamera() {
    const room = liveRoomRef.current;
    if (!room) return;
    const next = !cameraEnabled;
    await room.localParticipant.setCameraEnabled(next);
    setCameraEnabled(next);
  }

  async function toggleMic() {
    const room = liveRoomRef.current;
    if (!room) return;
    const next = !micEnabled;
    await room.localParticipant.setMicrophoneEnabled(next);
    setMicEnabled(next);
  }

  async function toggleScreen() {
    const room = liveRoomRef.current;
    if (!room) return;
    const next = !screenEnabled;
    await room.localParticipant.setScreenShareEnabled(next);
    setScreenEnabled(next);
  }

  async function copyRoomId(roomId: string) {
    await navigator.clipboard.writeText(roomId);
    setMessage(t("roomIdCopied"));
  }

  async function closeRoom(room: RealtimeRoom) {
    if (!window.confirm(t("closeConfirm"))) return;
    setBusy(`close:${room.id}`);
    try {
      if (selectedRoomId === room.id && connected) await leave();
      await closeRealtimeRoom(room.id);
      await loadRooms();
      setMessage(t("roomClosed"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  async function createRecording() {
    if (!selectedRoom) return;
    const title = window.prompt(t("recordingTitlePrompt"), `${selectedRoom.room_key} recording`);
    if (!title?.trim()) return;
    setBusy("recording-create");
    setError("");
    try {
      const row = await requestRealtimeRecording(selectedRoom.id, {
        title: title.trim(),
        idempotency_key: requestId("recording"),
        consent_version: "realtime-recording-v1",
        retention_days: 30,
      });
      setRecordings((current) => [row, ...current.filter((item) => item.id !== row.id)]);
      setMessage(t("recordingRequested"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  async function consent(recording: RealtimeRecording, value: boolean) {
    setBusy(`consent:${recording.id}`);
    setError("");
    try {
      const row = await setRealtimeRecordingConsent(recording.id, value);
      setRecordings((current) => current.map((item) => (item.id === row.id ? row : item)));
      setMessage(value ? t("consentRecorded") : t("consentDeclined"));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  async function stopRecording(recording: RealtimeRecording) {
    setBusy(`stop:${recording.id}`);
    setError("");
    try {
      const row = await stopRealtimeRecording(recording.id);
      setRecordings((current) => current.map((item) => (item.id === row.id ? row : item)));
    } catch (cause) {
      setError(errorText(cause, t("actionError")));
    } finally {
      setBusy(null);
    }
  }

  if (isLoading || (!isAuthenticated && !isLoading)) {
    return (
      <section className="page-shell py-16 text-white">
        <div className="glass-panel flex min-h-52 items-center justify-center rounded-3xl">
          <LoaderCircle className="h-7 w-7 animate-spin text-electric-200" />
        </div>
      </section>
    );
  }

  return (
    <section className="page-shell py-10 text-white sm:py-14">
      <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
        <div className="max-w-3xl">
          <span className="eyebrow"><Radio className="h-3.5 w-3.5" /> {t("eyebrow")}</span>
          <h1 className="section-title mt-6">{t("title")}</h1>
          <p className="section-copy mt-4">{t("description")}</p>
        </div>
        <Button variant="secondary" onClick={() => void loadRooms()} disabled={busy === "load"}>
          <RefreshCw className={`h-4 w-4 ${busy === "load" ? "animate-spin" : ""}`} /> {t("refresh")}
        </Button>
      </div>

      {error && <StatusMessage className="mt-6" tone="error">{error}</StatusMessage>}
      {message && <StatusMessage className="mt-6" tone="success">{message}</StatusMessage>}

      <Card className="mt-8">
        <CardContent>
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 text-electric-200" />
            <div>
              <p className="font-semibold">{t("runtimeTitle")}</p>
              <p className="mt-1 text-sm text-white/50">
                {readiness?.enabled ? t("runtimeReady") : t("runtimeOffline")}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="mt-8 grid gap-6 xl:grid-cols-[360px_1fr]">
        <div className="space-y-6">
          <Card>
            <CardContent>
              <h2 className="text-lg font-semibold">{t("createRoom")}</h2>
              <form className="mt-4 space-y-3" onSubmit={createRoom}>
                <Input name="room_key" required minLength={2} maxLength={160} placeholder={t("roomNamePlaceholder")} />
                <Button type="submit" className="w-full" disabled={!readiness?.enabled || busy === "create-room"}>
                  {busy === "create-room" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <PhoneCall className="h-4 w-4" />}
                  {t("create")}
                </Button>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <h2 className="text-lg font-semibold">{t("rooms")}</h2>
              <div className="mt-4 space-y-3">
                {rooms.length === 0 && <p className="text-sm text-white/45">{t("noRooms")}</p>}
                {rooms.map((room) => (
                  <button
                    key={room.id}
                    type="button"
                    className={`w-full rounded-2xl border p-4 text-start transition ${selectedRoomId === room.id ? "border-electric-300/35 bg-electric-500/10" : "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"}`}
                    onClick={() => setSelectedRoomId(room.id)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium">{room.room_key}</span>
                      <span className="text-xs text-white/45">{room.status}</span>
                    </div>
                    <p className="mt-2 text-xs text-white/40">{t("participants", { count: room.participant_count, max: room.max_participants })}</p>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardContent>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold">{selectedRoom?.room_key || t("selectRoom")}</h2>
                  {selectedRoom && (
                    <button type="button" onClick={() => void copyRoomId(selectedRoom.id)} className="mt-2 inline-flex items-center gap-2 text-xs text-white/45 hover:text-white">
                      <Copy className="h-3.5 w-3.5" /> {selectedRoom.id}
                    </button>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  {selectedRoom && !connected && selectedRoom.status === "open" && (
                    <Button onClick={() => void join(selectedRoom)} disabled={busy === `join:${selectedRoom.id}`}>
                      <PhoneCall className="h-4 w-4" /> {t("join")}
                    </Button>
                  )}
                  {connected && <Button variant="danger" onClick={() => void leave()}><PhoneOff className="h-4 w-4" /> {t("leave")}</Button>}
                  {selectedRoom && selectedRoom.created_by_id === user?.id && selectedRoom.status === "open" && (
                    <Button variant="secondary" onClick={() => void closeRoom(selectedRoom)}><CircleStop className="h-4 w-4" /> {t("close")}</Button>
                  )}
                </div>
              </div>

              {connected && (
                <div className="mt-5 flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={() => void toggleMic()}>{micEnabled ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4" />}{micEnabled ? t("mute") : t("unmute")}</Button>
                  <Button variant="secondary" onClick={() => void toggleCamera()}>{cameraEnabled ? <Camera className="h-4 w-4" /> : <CameraOff className="h-4 w-4" />}{cameraEnabled ? t("cameraOff") : t("cameraOn")}</Button>
                  {selectedRoom?.allow_screen_share && <Button variant="secondary" onClick={() => void toggleScreen()}><MonitorUp className="h-4 w-4" />{screenEnabled ? t("stopShare") : t("shareScreen")}</Button>}
                </div>
              )}

              <div ref={mediaRootRef} className="mt-6 grid min-h-64 gap-4 rounded-3xl border border-white/10 bg-black/30 p-4 md:grid-cols-2">
                {!connected && <div className="col-span-full flex min-h-56 items-center justify-center text-center text-sm text-white/35"><Video className="me-2 h-5 w-5" /> {t("mediaPlaceholder")}</div>}
              </div>
            </CardContent>
          </Card>

          {selectedRoom && (
            <Card>
              <CardContent>
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <h2 className="text-lg font-semibold">{t("recordings")}</h2>
                    <p className="mt-1 text-xs text-white/45">{t("recordingConsentNotice")}</p>
                  </div>
                  {selectedRoom.created_by_id === user?.id && connected && (
                    <Button variant="secondary" onClick={() => void createRecording()} disabled={busy === "recording-create"}>
                      <Radio className="h-4 w-4" /> {t("requestRecording")}
                    </Button>
                  )}
                </div>
                <div className="mt-5 space-y-3">
                  {recordings.length === 0 && <p className="text-sm text-white/45">{t("noRecordings")}</p>}
                  {recordings.map((recording) => (
                    <div key={recording.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="font-medium">{recording.title}</p>
                          <p className="mt-1 text-xs text-white/45">{t("consentProgress", { done: recording.consented_count, total: recording.required_consent_count })} · {recording.status}</p>
                          {recording.studio_asset_id && <p className="mt-1 text-xs text-green-200">{t("savedToStudio")}</p>}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {recording.status === "awaiting_consent" && (
                            <>
                              <Button size="sm" onClick={() => void consent(recording, true)} disabled={busy === `consent:${recording.id}`}>{t("agree")}</Button>
                              <Button size="sm" variant="danger" onClick={() => void consent(recording, false)} disabled={busy === `consent:${recording.id}`}>{t("decline")}</Button>
                            </>
                          )}
                          {selectedRoom.created_by_id === user?.id && ["starting", "active", "ending"].includes(recording.status) && (
                            <Button size="sm" variant="danger" onClick={() => void stopRecording(recording)} disabled={busy === `stop:${recording.id}`}><CircleStop className="h-3.5 w-3.5" /> {t("stopRecording")}</Button>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </section>
  );
}
