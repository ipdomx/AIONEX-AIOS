from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Mapping

from .contracts import Project3DBlueprint


@dataclass(frozen=True, slots=True)
class ScaffoldFile:
    path: str
    content: str

    def validate(self) -> None:
        rel = PurePosixPath(self.path)
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise ValueError("scaffold path must be project-relative and traversal-safe")


@dataclass(frozen=True, slots=True)
class RuntimeScaffold:
    project_id: str
    files: tuple[ScaffoldFile, ...]

    def validate(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id is required")
        seen: set[str] = set()
        for item in self.files:
            item.validate()
            if item.path in seen:
                raise ValueError(f"duplicate scaffold path: {item.path}")
            seen.add(item.path)
        required = {
            "package.json",
            "src/main.tsx",
            "src/App.tsx",
            "src/scene/World.tsx",
            "src/runtime/profile.ts",
            "src/controllers/PlayerController.tsx",
            "src/controllers/CameraController.tsx",
            "src/state/worldStore.ts",
            "src/overlays/ContentOverlay.tsx",
            "src/xr/WebXRBridge.tsx",
            "src/xr/XRControls.tsx",
            "src/generated/blueprint.ts",
        }
        missing = required - seen
        if missing:
            raise ValueError(f"incomplete 3D runtime scaffold: {sorted(missing)}")

    def as_mapping(self) -> Mapping[str, str]:
        return {item.path: item.content for item in self.files}


class ThreeDRuntimeScaffoldBuilder:
    """Generate a deterministic React Three Fiber runtime from a validated blueprint.

    The builder writes source only. It never installs packages, downloads assets, or claims
    that an external 3D optimizer/model generator executed.
    """

    def build(self, blueprint: Project3DBlueprint) -> RuntimeScaffold:
        blueprint.validate()
        bp = self._blueprint_source(blueprint)
        files = (
            ScaffoldFile("package.json", self._package_json(blueprint)),
            ScaffoldFile("package-lock.json", self._package_lock(blueprint)),
            ScaffoldFile("tsconfig.json", self._tsconfig()),
            ScaffoldFile("vite.config.ts", self._vite_config()),
            ScaffoldFile("index.html", self._index_html(blueprint.title)),
            ScaffoldFile("src/main.tsx", self._main()),
            ScaffoldFile("src/App.tsx", self._app()),
            ScaffoldFile("src/styles.css", self._styles()),
            ScaffoldFile("src/generated/blueprint.ts", bp),
            ScaffoldFile("src/state/worldStore.ts", self._store()),
            ScaffoldFile("src/runtime/profile.ts", self._runtime_profile()),
            ScaffoldFile("src/scene/World.tsx", self._world()),
            ScaffoldFile("src/scene/RuntimeProbe.tsx", self._runtime_probe()),
            ScaffoldFile("src/scene/Zone.tsx", self._zone()),
            ScaffoldFile("src/scene/AssetModel.tsx", self._asset_model()),
            ScaffoldFile("src/controllers/PlayerController.tsx", self._player_controller()),
            ScaffoldFile("src/controllers/CameraController.tsx", self._camera_controller()),
            ScaffoldFile("src/controllers/ResponsiveControls.tsx", self._responsive_controls()),
            ScaffoldFile("src/overlays/ContentOverlay.tsx", self._overlay()),
            ScaffoldFile("src/xr/WebXRBridge.tsx", self._webxr_bridge()),
            ScaffoldFile("src/xr/XRControls.tsx", self._xr_controls()),
        )
        scaffold = RuntimeScaffold(project_id=blueprint.project_id, files=files)
        scaffold.validate()
        return scaffold

    def materialize(self, scaffold: RuntimeScaffold, destination: Path) -> tuple[Path, ...]:
        scaffold.validate()
        root = destination.resolve()
        root.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for item in scaffold.files:
            rel = PurePosixPath(item.path)
            path = (root / Path(*rel.parts)).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError("scaffold output escaped destination") from exc
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item.content, encoding="utf-8")
            written.append(path)
        return tuple(written)

    @staticmethod
    def _package_json(blueprint: Project3DBlueprint) -> str:
        package = {
            "name": blueprint.project_id.lower().replace("_", "-"),
            "private": True,
            "version": "0.1.0",
            "type": "module",
            "scripts": {"dev": "vite", "build": "tsc -b && vite build", "preview": "vite preview"},
            "dependencies": {
                "@react-three/drei": "^10.7.6",
                "@react-three/fiber": "^9.3.0",
                "react": "^19.1.1",
                "react-dom": "^19.1.1",
                "three": "0.185.1",
                "zustand": "^5.0.8",
            },
            "devDependencies": {
                "@types/react": "^19.1.10",
                "@types/react-dom": "^19.1.7",
                "@types/three": "0.185.4",
                "@vitejs/plugin-react": "^5.0.2",
                "typescript": "^5.9.2",
                "vite": "^7.1.3",
            },
        }
        return json.dumps(package, indent=2, sort_keys=True) + "\n"

    @staticmethod
    def _package_lock(blueprint: Project3DBlueprint) -> str:
        template_path = Path(__file__).with_name("runtime-package-lock.json")
        payload = json.loads(template_path.read_text(encoding="utf-8"))
        package_name = blueprint.project_id.lower().replace("_", "-")
        payload["name"] = package_name
        payload["version"] = "0.1.0"
        root = payload.get("packages", {}).get("")
        if isinstance(root, dict):
            root["name"] = package_name
            root["version"] = "0.1.0"
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @staticmethod
    def _tsconfig() -> str:
        return '''{
  "compilerOptions": {
    "target": "ES2022", "useDefineForClassFields": true, "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "allowJs": false, "skipLibCheck": true, "esModuleInterop": true, "allowSyntheticDefaultImports": true,
    "strict": true, "forceConsistentCasingInFileNames": true, "module": "ESNext", "moduleResolution": "Bundler",
    "resolveJsonModule": true, "isolatedModules": true, "noEmit": true, "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": []
}
'''

    @staticmethod
    def _vite_config() -> str:
        return '''import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react()], build: { sourcemap: false } });
'''

    @staticmethod
    def _index_html(title: str) -> str:
        safe = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        return f'''<!doctype html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><meta name="theme-color" content="#07111f"/><link rel="icon" href="data:,"/><title>{safe}</title></head><body><div id="root"><section style="padding:2rem;color:white;background:#07111f;font-family:system-ui"><h1>{safe}</h1><p>Loading the interactive 3D experience…</p></section></div><noscript><main><h1>{safe}</h1><p>This 3D experience requires JavaScript. Accessible project content remains available from the delivery package.</p></main></noscript><script type="module" src="/src/main.tsx"></script></body></html>\n'''

    @staticmethod
    def _main() -> str:
        return '''import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
'''

    @staticmethod
    def _app() -> str:
        return '''import { Canvas } from "@react-three/fiber";
import { Suspense } from "react";
import { World } from "./scene/World";
import { ContentOverlay } from "./overlays/ContentOverlay";
import { XRControls } from "./xr/XRControls";
export default function App() {
  return <main className="app-shell">
    <Canvas dpr={1} gl={{ antialias: true, powerPreference: "high-performance" }} camera={{ position: [0, 5, 10], fov: 50 }}>
      <Suspense fallback={null}><World /></Suspense>
    </Canvas>
    <ContentOverlay />
    <XRControls />
  </main>;
}
'''


    @staticmethod
    def _webxr_bridge() -> str:
        return '''import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
type XRMode = "immersive-ar" | "immersive-vr";
type XRState = { secureContext:boolean; apiAvailable:boolean; arSupported:boolean; vrSupported:boolean; activeMode:XRMode|null; lastError:string|null };
type XRSessionLike = { addEventListener:(type:string, cb:()=>void, options?:{once?:boolean})=>void; end:()=>Promise<void> };
type XRSystemLike = { isSessionSupported:(mode:XRMode)=>Promise<boolean>; requestSession:(mode:XRMode, init:Record<string,unknown>)=>Promise<XRSessionLike> };
declare global { interface Window { __AIOS_XR_STATE__?:XRState; __AIOS_XR_REQUEST__?:(mode:XRMode)=>Promise<boolean>; __AIOS_XR_END__?:()=>Promise<boolean>; } }
function safeMessage(value:unknown){return value instanceof Error ? value.name : "xr-session-error"}
export function WebXRBridge(){const {gl}=useThree();useEffect(()=>{
  let alive=true; const nav=navigator as Navigator & {xr?:XRSystemLike}; gl.xr.enabled=true;
  const state:XRState={secureContext:window.isSecureContext,apiAvailable:Boolean(nav.xr),arSupported:false,vrSupported:false,activeMode:null,lastError:null}; window.__AIOS_XR_STATE__=state;
  const publish=()=>{window.__AIOS_XR_STATE__={...state}};
  const detect=async()=>{if(!state.secureContext||!nav.xr){publish();return}try{const [ar,vr]=await Promise.all([nav.xr.isSessionSupported("immersive-ar"),nav.xr.isSessionSupported("immersive-vr")]);if(!alive)return;state.arSupported=ar;state.vrSupported=vr;publish()}catch(e){state.lastError=safeMessage(e);publish()}};
  window.__AIOS_XR_REQUEST__=async(mode)=>{if(!window.isSecureContext||!nav.xr){state.lastError="xr-unavailable";publish();return false}const supported=mode==="immersive-ar"?state.arSupported:state.vrSupported;if(!supported){state.lastError="xr-mode-unsupported";publish();return false}try{const session=await nav.xr.requestSession(mode,{requiredFeatures:["local-floor"],optionalFeatures:["bounded-floor","hand-tracking","layers"]});await gl.xr.setSession(session as never);state.activeMode=mode;state.lastError=null;session.addEventListener("end",()=>{state.activeMode=null;publish()},{once:true});publish();return true}catch(e){state.lastError=safeMessage(e);publish();return false}};
  window.__AIOS_XR_END__=async()=>{const session=gl.xr.getSession() as unknown as XRSessionLike|null;if(!session)return false;await session.end();return true}; void detect();
  return()=>{alive=false;delete window.__AIOS_XR_REQUEST__;delete window.__AIOS_XR_END__;window.__AIOS_XR_STATE__=undefined;gl.xr.enabled=false};
},[gl]);return null}
'''

    @staticmethod
    def _xr_controls() -> str:
        return '''import { useEffect, useState } from "react";
type XRMode = "immersive-ar" | "immersive-vr";
type XRState = { secureContext:boolean; apiAvailable:boolean; arSupported:boolean; vrSupported:boolean; activeMode:XRMode|null; lastError:string|null };
declare global { interface Window { __AIOS_XR_STATE__?:XRState; __AIOS_XR_REQUEST__?:(mode:XRMode)=>Promise<boolean>; __AIOS_XR_END__?:()=>Promise<boolean>; } }
const EMPTY:XRState={secureContext:false,apiAvailable:false,arSupported:false,vrSupported:false,activeMode:null,lastError:null};
export function XRControls(){const [state,setState]=useState<XRState>(EMPTY);useEffect(()=>{const id=window.setInterval(()=>setState(window.__AIOS_XR_STATE__?{...window.__AIOS_XR_STATE__}:EMPTY),250);return()=>clearInterval(id)},[]);const request=(mode:XRMode)=>void window.__AIOS_XR_REQUEST__?.(mode);if(!state.secureContext)return <div data-aionex-xr="blocked">XR requires HTTPS secure context</div>;if(!state.apiAvailable||(!state.arSupported&&!state.vrSupported))return <div data-aionex-xr="device-required">XR device/runtime required</div>;return <div data-aionex-xr="ready">{state.arSupported&&<button onClick={()=>request("immersive-ar")}>Enter AR</button>}{state.vrSupported&&<button onClick={()=>request("immersive-vr")}>Enter VR</button>}{state.activeMode&&<button onClick={()=>void window.__AIOS_XR_END__?.()}>Exit XR</button>}</div>}
'''

    @staticmethod
    def _styles() -> str:
        return '''html,body,#root,.app-shell{width:100%;height:100%;margin:0;overflow:hidden}.app-shell{position:relative;background:#0b1020}.overlay{position:absolute;inset:0;pointer-events:none;color:white;font-family:system-ui,sans-serif}.overlay button,.overlay [data-interactive]{pointer-events:auto}.brand-panel{position:absolute;left:1rem;top:1rem;display:flex;flex-direction:column;gap:.2rem;padding:.8rem 1rem;border-radius:1rem;background:rgba(5,10,25,.72);backdrop-filter:blur(12px)}.brand-panel span{font-size:.75rem;opacity:.7}.overlay nav{position:absolute;right:1rem;top:1rem;display:flex;flex-wrap:wrap;justify-content:flex-end;gap:.45rem;max-width:min(70vw,52rem)}.overlay nav button{border:1px solid rgba(255,255,255,.14);background:rgba(7,17,31,.76);color:white;border-radius:999px;padding:.55rem .8rem}.zone-panel{position:absolute;left:1rem;bottom:1rem;max-width:28rem;padding:1rem;border-radius:1rem;background:rgba(5,10,25,.78);backdrop-filter:blur(12px)}.touch-pad{position:absolute;right:1rem;bottom:1rem;display:grid;grid-template-columns:repeat(3,3rem);gap:.4rem}@media(min-width:768px){.touch-pad{display:none}}
'''

    @staticmethod
    def _blueprint_source(blueprint: Project3DBlueprint) -> str:
        payload = {
            "projectId": blueprint.project_id,
            "title": blueprint.title,
            "objective": blueprint.objective,
            "playerController": blueprint.player_controller,
            "cameraMode": blueprint.camera_mode,
            "zones": [
                {
                    "id": z.zone_id,
                    "title": z.title,
                    "position": list(z.position),
                    "radius": z.radius,
                    "assetIds": list(z.asset_ids),
                    "mobileScale": z.mobile_scale,
                    "desktopScale": z.desktop_scale,
                    "interactions": sorted(i.value for i in z.interactions),
                }
                for z in blueprint.zones
            ],
            "assets": [
                {
                    "id": a.asset_id,
                    "kind": a.kind.value,
                    "path": "/" + (a.path[7:] if a.path.startswith("public/") else a.path).lstrip("/"),
                    "required": a.required,
                    "lazy": a.lazy,
                    "lodGroup": a.lod_group,
                }
                for a in blueprint.assets
            ],
        }
        encoded = json.dumps(payload, indent=2, ensure_ascii=False)
        return f'''export type AssetSpec = {{ id:string; kind:string; path:string; required:boolean; lazy:boolean; lodGroup:string|null }};\nexport type ZoneSpec = {{ id:string; title:string; position:[number,number,number]; radius:number; assetIds:string[]; mobileScale:number; desktopScale:number; interactions:string[] }};\nexport type BlueprintSpec = {{ projectId:string; title:string; objective:string; playerController:string; cameraMode:string; zones:ZoneSpec[]; assets:AssetSpec[] }};\nexport const blueprint: BlueprintSpec = {encoded};\nexport type ZoneId = string;\n'''

    @staticmethod
    def _store() -> str:
        return '''import { create } from "zustand";
import type { ZoneId } from "../generated/blueprint";
type Vec3 = [number, number, number];
type WorldState = {
  player: Vec3; activeZone: ZoneId | null; targetZone: ZoneId | null; input: Record<string, boolean>;
  setPlayer: (v: Vec3) => void; setActiveZone: (id: ZoneId | null) => void; setTargetZone: (id: ZoneId | null) => void;
  setInput: (key: string, pressed: boolean) => void;
};
export const useWorldStore = create<WorldState>((set) => ({
  player:[0,0,0], activeZone:null, targetZone:null, input:{},
  setPlayer:(player)=>set({player}), setActiveZone:(activeZone)=>set({activeZone}), setTargetZone:(targetZone)=>set({targetZone}),
  setInput:(key,pressed)=>set((s)=>({input:{...s.input,[key]:pressed}})),
}));
'''

    @staticmethod
    def _runtime_profile() -> str:
        return '''import { useEffect, useState } from "react";
export type RuntimeProfile = "desktop" | "mobile" | "low_power";
function detectProfile(): RuntimeProfile {
  const forced = new URLSearchParams(window.location.search).get("aionex_profile");
  if (forced === "desktop" || forced === "mobile" || forced === "low_power") return forced;
  const nav = navigator as Navigator & { deviceMemory?: number };
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || (nav.deviceMemory ?? 8) <= 4) return "low_power";
  return window.innerWidth < 768 ? "mobile" : "desktop";
}
export function useRuntimeProfile(): RuntimeProfile {
  const [profile, setProfile] = useState<RuntimeProfile>(() => typeof window === "undefined" ? "desktop" : detectProfile());
  useEffect(() => {
    const update = () => setProfile(detectProfile());
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return profile;
}
'''

    @staticmethod
    def _world() -> str:
        return '''import { blueprint } from "../generated/blueprint";
import { PlayerController } from "../controllers/PlayerController";
import { CameraController } from "../controllers/CameraController";
import { ResponsiveControls } from "../controllers/ResponsiveControls";
import { RuntimeProbe } from "./RuntimeProbe";
import { WebXRBridge } from "../xr/WebXRBridge";
import { Zone } from "./Zone";
export function World(){return <>
  <color attach="background" args={["#07111f"]}/><fog attach="fog" args={["#07111f",28,120]}/>
  <ambientLight intensity={0.75}/><hemisphereLight args={["#b9ddff","#0b1726",1.0]}/><directionalLight position={[8,14,5]} intensity={1.5}/>
  <gridHelper args={[180,90,"#1d4f70","#10283c"]} position={[0,-0.62,0]}/>
  {blueprint.zones.map((zone)=><Zone key={zone.id} zone={zone}/>) }
  <PlayerController/><CameraController/><ResponsiveControls/><RuntimeProbe/><WebXRBridge/>
</>}
'''

    @staticmethod
    def _runtime_probe() -> str:
        return '''import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
declare global { interface Window { __AIOS_3D_READY__?: boolean; __AIOS_3D_METRICS__?: Record<string, number>; } }
export function RuntimeProbe(){const {gl,camera}=useThree();const frames=useRef<number[]>([]);useEffect(()=>{window.__AIOS_3D_READY__=false;return()=>{window.__AIOS_3D_READY__=false}},[]);useFrame((_,dt)=>{
 const list=frames.current;list.push(dt);if(list.length>120)list.shift();if(list.length>=45){const avg=list.reduce((a,b)=>a+b,0)/list.length;window.__AIOS_3D_METRICS__={fps:avg>0?1/avg:0,frame_time_ms:avg*1000,draw_calls:gl.info.render.calls,triangles:gl.info.render.triangles,camera_x:camera.position.x,camera_y:camera.position.y,camera_z:camera.position.z};window.__AIOS_3D_READY__=true;}
});return null}
'''

    @staticmethod
    def _zone() -> str:
        return '''import { blueprint, type ZoneSpec } from "../generated/blueprint";
import { useRuntimeProfile } from "../runtime/profile";
import { useWorldStore } from "../state/worldStore";
import { AssetModel } from "./AssetModel";
export function Zone({zone}:{zone:ZoneSpec}){
  const setActiveZone=useWorldStore(s=>s.setActiveZone);
  const profile=useRuntimeProfile();
  const assets=blueprint.assets.filter(a=>zone.assetIds.includes(a.id));
  const scale=profile === "desktop" ? zone.desktopScale : zone.mobileScale;
  return <group position={zone.position} userData={{aionexZoneId:zone.id,aionexProfile:profile}} onPointerOver={()=>setActiveZone(zone.id)} onPointerOut={()=>setActiveZone(null)}>
    {assets.length?assets.map(a=><AssetModel key={a.id} asset={a} scale={scale} profile={profile}/>):<mesh><icosahedronGeometry args={[Math.max(0.8,Math.min(2.5,zone.radius/3)),2]}/><meshStandardMaterial color="#38bdf8" metalness={0.25} roughness={0.35}/></mesh>}
    <mesh rotation={[-Math.PI/2,0,0]} position={[0,-0.6,0]}><circleGeometry args={[zone.radius,48]}/><meshStandardMaterial color="#0f2b3e" transparent opacity={0.55}/></mesh>
  </group>;
}
'''

    @staticmethod
    def _asset_model() -> str:
        return '''import { useGLTF } from "@react-three/drei";
import type { AssetSpec } from "../generated/blueprint";
import type { RuntimeProfile } from "../runtime/profile";
export function AssetModel({asset,scale=1,profile}:{asset:AssetSpec;scale?:number;profile:RuntimeProfile}){
  if(asset.kind!=="glb"&&asset.kind!=="gltf") return null;
  if(profile==="low_power"&&asset.lazy) return <LowPowerProxy scale={scale}/>;
  return <Model path={asset.path} scale={scale}/>;
}
function LowPowerProxy({scale}:{scale:number}){return <mesh scale={Math.max(.5,scale)}><dodecahedronGeometry args={[1.2,1]}/><meshStandardMaterial color="#22d3ee" metalness={0.35} roughness={0.42}/></mesh>}
function Model({path,scale}:{path:string;scale:number}){const gltf=useGLTF(path);return <primitive object={gltf.scene.clone()} scale={scale}/>}
'''

    @staticmethod
    def _player_controller() -> str:
        return '''import { useFrame } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { blueprint } from "../generated/blueprint";
import { useWorldStore } from "../state/worldStore";
const SPEED=7, AUTO_SPEED=12;
export function PlayerController(){
  const ref=useRef<THREE.Group>(null); const input=useWorldStore(s=>s.input); const targetZone=useWorldStore(s=>s.targetZone); const setPlayer=useWorldStore(s=>s.setPlayer); const setInput=useWorldStore(s=>s.setInput);
  useEffect(()=>{const down=(e:KeyboardEvent)=>setInput(e.key,true),up=(e:KeyboardEvent)=>setInput(e.key,false);addEventListener("keydown",down);addEventListener("keyup",up);return()=>{removeEventListener("keydown",down);removeEventListener("keyup",up)}},[setInput]);
  useFrame((_,dt)=>{if(!ref.current)return; const p=ref.current.position; const target=targetZone?blueprint.zones.find(z=>z.id===targetZone):undefined;
    if(target){const t=new THREE.Vector3(...target.position); const d=t.sub(p); if(d.length()>target.radius*.5)p.add(d.normalize().multiplyScalar(AUTO_SPEED*dt));}
    else {const x=(input.ArrowRight||input.d?1:0)-(input.ArrowLeft||input.a?1:0);const z=(input.ArrowDown||input.s?1:0)-(input.ArrowUp||input.w?1:0); const d=new THREE.Vector3(x,0,z);if(d.lengthSq())p.add(d.normalize().multiplyScalar(SPEED*dt));}
    setPlayer([p.x,p.y,p.z]);
  });
  return <group ref={ref}><mesh castShadow><capsuleGeometry args={[.45,.8,6,12]}/><meshStandardMaterial color="#7dd3fc"/></mesh></group>;
}
'''

    @staticmethod
    def _camera_controller() -> str:
        return '''import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { useWorldStore } from "../state/worldStore";
const offset=new THREE.Vector3(0,5,9), desired=new THREE.Vector3(), look=new THREE.Vector3();
export function CameraController(){const {camera}=useThree();const player=useWorldStore(s=>s.player);useFrame((_,dt)=>{look.set(...player);desired.copy(look).add(offset);camera.position.lerp(desired,1-Math.exp(-5*dt));camera.lookAt(look)});return null}
'''

    @staticmethod
    def _responsive_controls() -> str:
        return '''import { useThree } from "@react-three/fiber";
import { useEffect } from "react";
import { useWorldStore } from "../state/worldStore";
export function ResponsiveControls(){const setInput=useWorldStore(s=>s.setInput);const {gl}=useThree();useEffect(()=>{const el=gl.domElement;
 const wheel=(e:WheelEvent)=>setInput(e.deltaY<0?"ArrowUp":"ArrowDown",true);const wheelEnd=()=>{setInput("ArrowUp",false);setInput("ArrowDown",false)};
 const pointer=()=>setInput("pointer",true),pointerUp=()=>setInput("pointer",false);el.addEventListener("wheel",wheel,{passive:true});el.addEventListener("pointerdown",pointer);addEventListener("pointerup",pointerUp);addEventListener("scroll",wheelEnd,{passive:true});return()=>{el.removeEventListener("wheel",wheel);el.removeEventListener("pointerdown",pointer);removeEventListener("pointerup",pointerUp);removeEventListener("scroll",wheelEnd)}},[gl,setInput]);return null}
'''

    @staticmethod
    def _overlay() -> str:
        return '''import { blueprint } from "../generated/blueprint";
import { useWorldStore } from "../state/worldStore";
declare global { interface Window { __AIOS_TARGET_ZONE__?: string | null; } }
export function ContentOverlay(){const active=useWorldStore(s=>s.activeZone);const setTargetStore=useWorldStore(s=>s.setTargetZone);const setInput=useWorldStore(s=>s.setInput);const zone=blueprint.zones.find(z=>z.id===active);
 const setTarget=(id:string|null)=>{window.__AIOS_TARGET_ZONE__=id;setTargetStore(id)};
 const press=(key:string)=>(e:React.PointerEvent)=>{e.preventDefault();setInput(key,true)}; const release=(key:string)=>()=>setInput(key,false);
 return <div className="overlay" aria-live="polite"><header className="brand-panel"><strong>{blueprint.title}</strong><span>{blueprint.zones.length} interactive zones</span></header><nav data-interactive aria-label="3D zones">{blueprint.zones.map(z=><button data-zone-id={z.id} key={z.id} onClick={()=>setTarget(z.id)}>{z.title}</button>)}</nav>{zone&&<section className="zone-panel"><h1>{zone.title}</h1><p>{blueprint.objective}</p><button data-interactive onClick={()=>setTarget(null)}>Manual navigation</button></section>}
 <div className="touch-pad" data-interactive><span/><button aria-label="Move forward" onPointerDown={press("ArrowUp")} onPointerUp={release("ArrowUp")}>↑</button><span/><button aria-label="Move left" onPointerDown={press("ArrowLeft")} onPointerUp={release("ArrowLeft")}>←</button><button aria-label="Move backward" onPointerDown={press("ArrowDown")} onPointerUp={release("ArrowDown")}>↓</button><button aria-label="Move right" onPointerDown={press("ArrowRight")} onPointerUp={release("ArrowRight")}>→</button></div></div>;
}
'''
