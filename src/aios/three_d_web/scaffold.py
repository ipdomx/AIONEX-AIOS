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
            "src/controllers/PlayerController.tsx",
            "src/controllers/CameraController.tsx",
            "src/state/worldStore.ts",
            "src/overlays/ContentOverlay.tsx",
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
            ScaffoldFile("tsconfig.json", self._tsconfig()),
            ScaffoldFile("vite.config.ts", self._vite_config()),
            ScaffoldFile("index.html", self._index_html(blueprint.title)),
            ScaffoldFile("src/main.tsx", self._main()),
            ScaffoldFile("src/App.tsx", self._app()),
            ScaffoldFile("src/styles.css", self._styles()),
            ScaffoldFile("src/generated/blueprint.ts", bp),
            ScaffoldFile("src/state/worldStore.ts", self._store()),
            ScaffoldFile("src/scene/World.tsx", self._world()),
            ScaffoldFile("src/scene/Zone.tsx", self._zone()),
            ScaffoldFile("src/scene/AssetModel.tsx", self._asset_model()),
            ScaffoldFile("src/controllers/PlayerController.tsx", self._player_controller()),
            ScaffoldFile("src/controllers/CameraController.tsx", self._camera_controller()),
            ScaffoldFile("src/controllers/ResponsiveControls.tsx", self._responsive_controls()),
            ScaffoldFile("src/overlays/ContentOverlay.tsx", self._overlay()),
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
                "three": "^0.179.1",
                "zustand": "^5.0.8",
            },
            "devDependencies": {
                "@types/react": "^19.1.10",
                "@types/react-dom": "^19.1.7",
                "@types/three": "^0.179.0",
                "@vitejs/plugin-react": "^5.0.2",
                "typescript": "^5.9.2",
                "vite": "^7.1.3",
            },
        }
        return json.dumps(package, indent=2, sort_keys=True) + "\n"

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
        return f'''<!doctype html><html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>{safe}</title></head><body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body></html>\n'''

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
export default function App() {
  return <main className="app-shell">
    <Canvas shadows dpr={[1, 2]} camera={{ position: [0, 5, 10], fov: 50 }}>
      <Suspense fallback={null}><World /></Suspense>
    </Canvas>
    <ContentOverlay />
  </main>;
}
'''

    @staticmethod
    def _styles() -> str:
        return '''html,body,#root,.app-shell{width:100%;height:100%;margin:0;overflow:hidden}.app-shell{position:relative;background:#0b1020}.overlay{position:absolute;inset:0;pointer-events:none;color:white;font-family:system-ui,sans-serif}.overlay button,.overlay [data-interactive]{pointer-events:auto}.zone-panel{position:absolute;left:1rem;bottom:1rem;max-width:28rem;padding:1rem;border-radius:1rem;background:rgba(5,10,25,.78);backdrop-filter:blur(12px)}.touch-pad{position:absolute;right:1rem;bottom:1rem;display:grid;grid-template-columns:repeat(3,3rem);gap:.4rem}@media(min-width:768px){.touch-pad{display:none}}
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
                    "path": "/" + a.path.lstrip("/"),
                    "required": a.required,
                    "lazy": a.lazy,
                    "lodGroup": a.lod_group,
                }
                for a in blueprint.assets
            ],
        }
        encoded = json.dumps(payload, indent=2, ensure_ascii=False)
        return f'''export const blueprint = {encoded} as const;\nexport type ZoneId = typeof blueprint.zones[number]["id"];\n'''

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
    def _world() -> str:
        return '''import { Environment } from "@react-three/drei";
import { blueprint } from "../generated/blueprint";
import { PlayerController } from "../controllers/PlayerController";
import { CameraController } from "../controllers/CameraController";
import { ResponsiveControls } from "../controllers/ResponsiveControls";
import { Zone } from "./Zone";
export function World(){return <>
  <ambientLight intensity={0.7}/><directionalLight castShadow position={[8,14,5]} intensity={1.5}/>
  <Environment preset="city"/>
  {blueprint.zones.map((zone)=><Zone key={zone.id} zone={zone}/>) }
  <PlayerController/><CameraController/><ResponsiveControls/>
</>}
'''

    @staticmethod
    def _zone() -> str:
        return '''import { blueprint } from "../generated/blueprint";
import { useWorldStore } from "../state/worldStore";
import { AssetModel } from "./AssetModel";
type ZoneSpec = typeof blueprint.zones[number];
export function Zone({zone}:{zone:ZoneSpec}){
  const setActiveZone=useWorldStore(s=>s.setActiveZone);
  const assets=blueprint.assets.filter(a=>zone.assetIds.includes(a.id));
  return <group position={zone.position} onPointerOver={()=>setActiveZone(zone.id)} onPointerOut={()=>setActiveZone(null)}>
    {assets.map(a=><AssetModel key={a.id} asset={a} scale={zone.desktopScale}/>) }
  </group>;
}
'''

    @staticmethod
    def _asset_model() -> str:
        return '''import { useGLTF } from "@react-three/drei";
import { blueprint } from "../generated/blueprint";
type AssetSpec = typeof blueprint.assets[number];
export function AssetModel({asset,scale=1}:{asset:AssetSpec;scale?:number}){
  if(asset.kind!=="glb"&&asset.kind!=="gltf") return null;
  return <Model path={asset.path} scale={scale}/>;
}
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
export function ContentOverlay(){const active=useWorldStore(s=>s.activeZone);const setTarget=useWorldStore(s=>s.setTargetZone);const setInput=useWorldStore(s=>s.setInput);const zone=blueprint.zones.find(z=>z.id===active);
 const press=(key:string)=>(e:React.PointerEvent)=>{e.preventDefault();setInput(key,true)}; const release=(key:string)=>()=>setInput(key,false);
 return <div className="overlay" aria-live="polite"><nav data-interactive>{blueprint.zones.map(z=><button key={z.id} onClick={()=>setTarget(z.id)}>{z.title}</button>)}</nav>{zone&&<section className="zone-panel"><h1>{zone.title}</h1><p>{blueprint.objective}</p><button onClick={()=>setTarget(null)}>Manual navigation</button></section>}
 <div className="touch-pad" data-interactive><span/><button onPointerDown={press("ArrowUp")} onPointerUp={release("ArrowUp")}>↑</button><span/><button onPointerDown={press("ArrowLeft")} onPointerUp={release("ArrowLeft")}>←</button><button onPointerDown={press("ArrowDown")} onPointerUp={release("ArrowDown")}>↓</button><button onPointerDown={press("ArrowRight")} onPointerUp={release("ArrowRight")}>→</button></div></div>;
}
'''
