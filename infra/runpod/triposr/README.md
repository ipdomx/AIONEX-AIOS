# AIONEX TripoSR fallback worker

Commercially permissive fallback for jurisdictions where Tencent Hunyuan3D 2.1 is not licensed or when Owner policy disables the primary provider. The vendored source is pinned to TripoSR commit `107cefdc244c39106fa830359024f6a2f1c78871`; the model snapshot is pinned to Hugging Face revision `5b521936b01fbe1890f6f9baed0254ab6351c04a`. Both upstream source and model card identify the license as MIT. The MIT license is retained under `vendor/LICENSE`.

This fallback returns a valid GLB using TripoSR vertex colors. It is not represented as Hunyuan PBR output; the response manifest explicitly reports `fallback_used=true`, `fallback_provider=triposr`, and `pbr_material_count=0`.
