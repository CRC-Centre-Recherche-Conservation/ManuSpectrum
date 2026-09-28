/** The steps of the blue heat ramp of Compare's counted tables (`--heat-1` … `--heat-4`). */
export const HEAT_STEPS = 4;

/** The step of `count` on a ramp whose largest count is `max`: 1 to `HEAT_STEPS`, the largest on the last; 0 for an empty count. */
export function heatLevel(count: number, max: number): number {
    if (count <= 0 || max <= 0) return 0;
    return Math.min(HEAT_STEPS, Math.ceil((HEAT_STEPS * count) / max));
}
