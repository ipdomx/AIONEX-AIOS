# FR-06C4C3A — isolated candidate runtime reconstruction

This source-only gate reconstructs the clean encrypted Docker/containerd candidate while production stays on the retained legacy runtime. It uses separate roots, sockets, exec/state directories, no bridge and no iptables mutation. Seven external images are pulled by digest and ten local authorities are rebuilt from the exact accepted source. Historical Docker/containerd roots are never copied and no application container may remain in the candidate. Live cutover belongs to FR-06C4C3B.
