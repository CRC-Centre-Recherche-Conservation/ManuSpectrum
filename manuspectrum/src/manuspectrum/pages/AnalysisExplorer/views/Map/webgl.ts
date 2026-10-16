/** Whether this browser can open a WebGL context (MapLibre 4 needs one); a context refused or throwing means no. */
export function webglAvailable(
    make: () => HTMLCanvasElement = () => document.createElement("canvas"),
): boolean {
    try {
        const canvas = make();
        const context =
            canvas.getContext("webgl2") ?? canvas.getContext("webgl");
        return context !== null;
    } catch {
        return false;
    }
}
