/*
 * Console script of `annotation_frames verify --refused-out`: reads the
 * info.json of the image services of one host that refuses the server, from a
 * browser tab on that host's origin, and copies the raw fields as JSON for
 * `--frames FILE`. It compares nothing, makes no other request and writes
 * nothing.
 */
(async () => {
  const SERVICES = __SERVICES__;
  const KEPT = ["width", "height", "tiles", "tile_width"];
  const frames = [];
  const failed = [];
  for (let n = 0; n < SERVICES.length; n += 1) {
    if (n > 0) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    const service = SERVICES[n];
    try {
      const response = await fetch(service + "/info.json", {
        credentials: "omit",
      });
      if (response.ok) {
        const body = await response.json();
        const info = {};
        for (const key of KEPT) {
          if (body && body[key] !== undefined) {
            info[key] = body[key];
          }
        }
        frames.push({ service, info });
      } else {
        failed.push([service, "HTTP " + response.status]);
      }
    } catch (error) {
      failed.push([service, String(error)]);
    }
    console.log(n + 1 + " / " + SERVICES.length);
  }
  const result = {
    version: 1,
    measured_at: new Date().toISOString(),
    origin: location.origin,
    frames,
    failed,
  };
  const text = JSON.stringify(result, null, 2);
  window.msFrames = result;
  console.log(text);
  try {
    copy(text);
  } catch (error) {
    console.log("copy() is not available: select the JSON above and copy it.");
  }
})();
