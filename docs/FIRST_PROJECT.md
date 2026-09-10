# First SolomonPrime project

1. Inventory every physical drive, filesystem, mount, free-space region, file tree, and relevant health metadata.
2. Do not mount unmounted drives writable during discovery.
3. Classify data into active/hot, working/bulk, archive/evidence, backup, model, dataset, and unknown categories.
4. Detect probable duplicates by file size and sampled hash; verify exact duplicates with full BLAKE3/SHA-256 before proposing reclamation.
5. Produce a canonical layout proposal with exact source/destination paths and estimated reclaimed space.
6. Critic/Evaluator independently reviews every high-impact migration plan.
7. Require human approval before important moves, deletions, filesystem changes, mounts, or archive pruning.
8. Verify copied data and provenance before originals become eligible for removal.
9. In parallel, inventory SolomonPrime memory, deduplicate redundant records, preserve contradictions/provenance, and benchmark retrieval effectiveness.
