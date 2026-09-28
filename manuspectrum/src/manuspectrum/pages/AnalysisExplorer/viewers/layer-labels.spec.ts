import { describe, expect, it } from "vitest";

import { layerKindLabel } from "@/manuspectrum/pages/AnalysisExplorer/viewers/layer-labels.ts";

const gettext = (msgid: string): string => `«${msgid}»`;

describe("layer labels", () => {
    it("names a layer by its kind", () => {
        expect(
            (["element", "band", "other"] as const).map((kind) =>
                layerKindLabel(gettext, kind),
            ),
        ).toEqual(["«Element»", "«Band»", "«Layer»"]);
    });
});
