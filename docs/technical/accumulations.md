# Accumulation Logic

Precipitation and snow fields in FA files are typically "total accumulations since the start of the run" (index H00). To be useful for meteorologists and visualization tools, these must be "decumulated" into specific time windows (e.g., 3h, 6h, etc.).

## 1. Sliding Window Calculation

The converter implements a **sliding window** logic. For a given duration $N$ (e.g., 3 hours), the value at time $T$ is calculated as:

$$RR_{N}(T) = Acc(T) - Acc(T - N)$$

Where:
- $Acc(T)$ is the total accumulation at time $T$.
- $Acc(T - N)$ is the total accumulation $N$ hours earlier.

**Example (3h accumulation):**
- At H03: `RR3h = Acc(H03) - Acc(H00)`
- At H06: `RR3h = Acc(H06) - Acc(H03)`
- At H09: `RR3h = Acc(H09) - Acc(H06)`

## 2. Zarr Group Partitioning

Variables are grouped by duration into dedicated Zarr stores (e.g., `surface_3h.zarr`). 

### Time Slicing (Eliminating NaNs)
Because the sliding window requires a leadtime $T - N$, the first $N$ hours of a run do not have valid data for an $N$-hour accumulation.

- **3h Group**: Sliced to start at **H03**.
- **6h Group**: Sliced to start at **H06**.
- **12h Group**: Sliced to start at **H12**.

This ensures that index `0` in a duration-specific Zarr group always corresponds to the first valid measurement.

## 3. Storage Hierarchy

```text
zarr/arome/2026030100/
├── surface.zarr/         # Instantaneous (2t, ps, etc.)
├── surface_3h.zarr/      # tp, tsnowp (decumulated 3h, starts H03)
├── surface_6h.zarr/      # tp, tsnowp (decumulated 6h, starts H06)
└── ...
```

In each group, the variable names are standardized back to their original name (e.g., `tp` instead of `RR3h`) using the `shortname` metadata from `fa_definitions.json`.
