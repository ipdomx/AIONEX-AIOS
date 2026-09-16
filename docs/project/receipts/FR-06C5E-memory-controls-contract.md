# FR-06C5E memory controls

A fresh 8 GiB backing file is used for random-key dm-crypt swap rather than encrypting the old `/swap.img` in place. The old swap file is retained inactive only for rollback; no secure-erasure claim is made. `/tmp` becomes tmpfs only after a zero-hidden-underlay-FD gate.
