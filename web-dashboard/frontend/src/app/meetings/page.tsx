"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertCircle, CalendarClock, CheckCircle2, Loader2, MapPin, Users } from "lucide-react";

import { MeetingSummary, runtimeServices } from "@/lib/runtime-services";

export default function MeetingsPage() {
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await runtimeServices.listMeetings({ limit: 100 });
        if (!cancelled) setMeetings(data);
      } catch (requestError) {
        if (!cancelled) setError(requestError instanceof Error ? requestError.message : "Failed to load meetings");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold text-white tracking-tight">Meetings</h1>
        <p className="text-sm text-white/40 mt-1">Owner-governed meetings from the AIOS runtime</p>
      </motion.div>
      {loading && <div className="glass-card p-8 flex items-center justify-center gap-3 text-white/60"><Loader2 className="w-5 h-5 animate-spin" />Loading meetings...</div>}
      {error && <div className="glass-card p-5 border border-red-500/20 flex items-start gap-3 text-red-300"><AlertCircle className="w-5 h-5" /><span>{error}</span></div>}
      {!loading && !error && <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">{meetings.map((meeting, index) => <motion.div key={meeting.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.05 }} className="glass-card p-5"><div className="flex items-start justify-between gap-4"><div><div className="flex items-center gap-3"><div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20"><CalendarClock className="w-5 h-5 text-blue-400" /></div><div><h2 className="text-sm font-semibold text-white">{meeting.title}</h2><p className="text-xs text-white/40">{meeting.status.replace("_", " ")}</p></div></div><p className="text-xs text-white/40 mt-4">{meeting.description || "No description"}</p><div className="space-y-2 mt-4 text-xs text-white/40"><div className="flex items-center gap-2"><Users className="w-3.5 h-3.5" />{meeting.organizer}</div><div className="flex items-center gap-2"><CalendarClock className="w-3.5 h-3.5" />{meeting.start_time}</div><div className="flex items-center gap-2"><MapPin className="w-3.5 h-3.5" />{meeting.location || "No location"}</div></div></div>{meeting.approved_by_owner && <div className="flex items-center gap-1 text-xs text-green-400"><CheckCircle2 className="w-4 h-4" />Owner approved</div>}</div></motion.div>)}</div>}
    </div>
  );
}
