/**
 * Vitest unit spec — views/components/functions/imaging-layers-proposal.js.
 *
 * The read-only panel: it registers its component and lists the nodegroups it is bound to.
 */
import { beforeAll, describe, expect, it, vi } from "vitest";
import ko from "knockout";

vi.mock(
    "templates/views/components/functions/imaging-layers-proposal.htm",
    () => ({
        default: "<div></div>",
    }),
);

let registered;
let ViewModel;

beforeAll(async () => {
    const spy = vi
        .spyOn(ko.components, "register")
        .mockImplementation((name, config) => {
            registered = { name, config };
        });
    ViewModel = (await import("./imaging-layers-proposal.js")).default;
    spy.mockRestore();
});

describe("imaging-layers-proposal", () => {
    it("registers its component under the path the function names", () => {
        expect(registered.name).toBe(
            "views/components/functions/imaging-layers-proposal",
        );
        expect(registered.config.viewModel).toBe(ViewModel);
    });

    it("lists the triggering nodegroups, observable or not", () => {
        expect(
            new ViewModel({
                config: { triggering_nodegroups: ["a"] },
            }).triggeringNodegroups(),
        ).toEqual(["a"]);
        expect(
            new ViewModel({
                config: { triggering_nodegroups: ko.observable(["b"]) },
            }).triggeringNodegroups(),
        ).toEqual(["b"]);
        expect(new ViewModel({ config: {} }).triggeringNodegroups()).toEqual(
            [],
        );
    });
});
