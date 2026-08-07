"use client";
import {useEffect,useState} from "react";
import {runtimeServices,ProviderSummary} from "@/lib/runtime-services";
import {LiveDataPanel,JsonCard} from "@/components/system/LiveDataPanel";
export default function Page(){const[d,setD]=useState<ProviderSummary[]>([]),[e,setE]=useState<string|null>(null),[l,setL]=useState(true);useEffect(()=>{runtimeServices.listProviders().then(setD).catch(x=>setE(x.message)).finally(()=>setL(false))},[]);return <LiveDataPanel title="AI Usage" subtitle="Live provider usage, limits and last-use evidence." loading={l} error={e} empty={!d.length}><div className="grid gap-4 xl:grid-cols-2">{d.map(x=><JsonCard key={x.id} title={x.name} value={{type:x.type,status:x.status,enabled:x.enabled,usage_today:x.usage_today,usage_limit:x.usage_limit,last_used:x.last_used,cost_per_1k_tokens:x.cost_per_1k_tokens}}/>)}</div></LiveDataPanel>}
