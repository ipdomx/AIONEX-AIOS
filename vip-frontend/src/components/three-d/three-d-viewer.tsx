"use client";

import { useEffect, useRef, useState } from "react";
import { RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

export function disposeObject(root: THREE.Object3D) {
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh)) return;
    object.geometry?.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (value instanceof THREE.Texture) value.dispose();
      }
      material.dispose();
    }
  });
}

interface ViewerControls {
  reset: () => void;
  zoom: (factor: number) => void;
}

export interface ThreeDViewerLabels {
  /** Accessible name of the viewport and the message shown when loading fails. */
  error: string;
  /** Accessible name of the viewport; falls back to `error` for older callers. */
  viewport?: string;
  reset?: string;
  zoomIn?: string;
  zoomOut?: string;
  loading?: string;
}

/**
 * Shared GLB viewer (three.js + GLTFLoader + OrbitControls) used by the
 * Projects 3D panel and the standalone 3D page. Every GPU resource it creates
 * is released when the URL changes or the component unmounts.
 */
export function ThreeDViewer({
  url,
  labels,
  className = "mt-4",
  heightClassName = "h-72 sm:h-80",
  onModelChange,
}: {
  url: string;
  labels: ThreeDViewerLabels;
  className?: string;
  heightClassName?: string;
  onModelChange?: (model: THREE.Object3D | null) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const controlsRef = useRef<ViewerControls | null>(null);
  const modelCallbackRef = useRef(onModelChange);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    modelCallbackRef.current = onModelChange;
  }, [onModelChange]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !url) return;
    setFailed(false);
    setLoaded(false);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000);
    camera.position.set(2.5, 1.8, 2.5);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 0.25;
    controls.maxDistance = 20;
    controls.listenToKeyEvents(container);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2));
    const key = new THREE.DirectionalLight(0xffffff, 2.5);
    key.position.set(4, 6, 4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 1.25);
    fill.position.set(-4, 2, -3);
    scene.add(fill);

    let model: THREE.Object3D | null = null;
    let frame = 0;
    let disposed = false;
    const home = new THREE.Vector3(2.5, 1.8, 2.5);
    const resize = () => {
      const width = Math.max(1, container.clientWidth);
      const height = Math.max(1, container.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    controlsRef.current = {
      reset: () => {
        camera.position.copy(home);
        controls.target.set(0, 0, 0);
        controls.update();
      },
      zoom: (factor: number) => {
        const offset = camera.position.clone().sub(controls.target);
        const distance = Math.min(
          controls.maxDistance,
          Math.max(controls.minDistance, offset.length() * factor),
        );
        camera.position.copy(controls.target).add(offset.setLength(distance));
        controls.update();
      },
    };

    new GLTFLoader().load(
      url,
      (gltf) => {
        if (disposed) {
          disposeObject(gltf.scene);
          return;
        }
        model = gltf.scene;
        scene.add(model);
        const box = new THREE.Box3().setFromObject(model);
        const sphere = box.getBoundingSphere(new THREE.Sphere());
        const radius = Math.max(sphere.radius, 0.1);
        model.position.sub(sphere.center);
        camera.near = Math.max(radius / 100, 0.001);
        camera.far = Math.max(radius * 100, 100);
        controls.minDistance = Math.max(radius * 0.25, 0.01);
        controls.maxDistance = Math.max(radius * 20, 20);
        home.set(radius * 2.4, radius * 1.6, radius * 2.4);
        camera.position.copy(home);
        camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0);
        controls.update();
        setLoaded(true);
        modelCallbackRef.current?.(model);
      },
      undefined,
      () => {
        if (!disposed) setFailed(true);
      },
    );

    const animate = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = window.requestAnimationFrame(animate);
    };
    animate();
    return () => {
      disposed = true;
      controlsRef.current = null;
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      controls.stopListenToKeyEvents();
      controls.dispose();
      if (model) {
        scene.remove(model);
        disposeObject(model);
        modelCallbackRef.current?.(null);
      }
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [url]);

  const viewportLabel = labels.viewport || labels.error;
  const toolbar = Boolean(labels.reset || labels.zoomIn || labels.zoomOut);

  return (
    <div className={`relative overflow-hidden rounded-2xl border border-white/[0.08] bg-black/20 ${className}`}>
      <div
        ref={containerRef}
        className={`${heightClassName} w-full touch-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-crimson-500`}
        role="application"
        aria-label={viewportLabel}
        tabIndex={0}
      />
      {toolbar && loaded && !failed && (
        <div className="absolute end-3 top-3 flex gap-1.5" dir="ltr">
          {labels.zoomIn && (
            <button
              type="button"
              onClick={() => controlsRef.current?.zoom(0.8)}
              aria-label={labels.zoomIn}
              title={labels.zoomIn}
              className="icon-button h-9 w-9 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
            >
              <ZoomIn className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          {labels.zoomOut && (
            <button
              type="button"
              onClick={() => controlsRef.current?.zoom(1.25)}
              aria-label={labels.zoomOut}
              title={labels.zoomOut}
              className="icon-button h-9 w-9 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
            >
              <ZoomOut className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          {labels.reset && (
            <button
              type="button"
              onClick={() => controlsRef.current?.reset()}
              aria-label={labels.reset}
              title={labels.reset}
              className="icon-button h-9 w-9 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-500"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>
      )}
      {!loaded && !failed && labels.loading && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-xs text-white/40" role="status">
          {labels.loading}
        </div>
      )}
      {failed && (
        <div className="absolute inset-0 grid place-items-center bg-obsidian-950/90 px-8 text-center text-xs text-white/55" role="alert">
          {labels.error}
        </div>
      )}
    </div>
  );
}
