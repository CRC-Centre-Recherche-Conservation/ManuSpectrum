import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";

import PrimeVue from "primevue/config";
import ConfirmationService from "primevue/confirmationservice";

import FieldRow from "@/manuspectrum/functions/SummaryConfigForm/components/FieldRow.vue";
import RollupEditor from "@/manuspectrum/functions/SummaryConfigForm/components/RollupEditor.vue";
import SummaryConfigForm from "@/manuspectrum/functions/SummaryConfigForm/SummaryConfigForm.vue";

import {
    ConfigConflictError,
    blankHop,
    csrfToken,
    defaultStyleFor,
    emptyConfig,
    fetchConfig,
    fetchRelations,
    involvedGraphs,
    knownAliases,
    removeConfig,
    saveConfig,
} from "@/manuspectrum/functions/summary-config-api.ts";

import type { ComponentPublicInstance, Plugin } from "vue";

import type {
    RelatableNodes,
    SummaryAggregate,
    SummaryConfig,
    SummaryConfigResponse,
    SummaryHop,
} from "@/manuspectrum/functions/types.ts";

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (
        urlName: string,
        urlParameters: { [key: string]: string | number },
    ) => `/en/${urlName}/${urlParameters.graphid}`,
}));

// PrimeVue's Select subscribes to a media query when it mounts; jsdom ships no
// matchMedia, and the rejection it throws tears the component down.
vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
}));

// Every form is unmounted after its test, so its ConfirmDialog leaves
// PrimeVue's module-wide confirmation bus and the next test's dialog is the
// only one listening.
enableAutoUnmount(afterEach);

const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const CONFIG_URL = `/en/manuspectrum:summary-config/${GRAPH_ID}`;
const RELATIONS_URL = `/en/manuspectrum:relatable-nodes/${GRAPH_ID}`;
const FORM_PLUGINS: (Plugin | [Plugin, ...unknown[]])[] = [
    [PrimeVue, { unstyled: true }],
    ConfirmationService,
];

function relations(): RelatableNodes {
    return {
        graph: { graphid: GRAPH_ID, slug: "document", name: "Document" },
        fields: [
            { alias: "label_of_name", datatype: "string", label: "Title" },
            {
                alias: "period_production",
                datatype: "reference",
                label: "Period",
            },
            {
                alias: "current_location",
                datatype: "resource-instance",
                label: "Location",
            },
        ],
        outgoing: [
            {
                alias: "current_location",
                label: "Location",
                targets: [
                    {
                        graphid: "22222222-2222-4222-8222-222222222222",
                        slug: "place",
                        name: "Place",
                    },
                ],
            },
        ],
        incoming: [
            {
                graph_slug: "component",
                graph_name: "Component",
                alias: "item_visual_is_part_of_document",
                label: "Part of document",
            },
        ],
        aggregatable: {
            document: [{ alias: "period_production", label: "Period" }],
            component: [{ alias: "color_features", label: "Colour" }],
            place: [],
        },
    };
}

function storedConfig(): SummaryConfig {
    return {
        config_version: 1,
        fields: [
            { alias: "label_of_name", style: "text" },
            { alias: "period_production", style: "chip", max_values: 3 },
        ],
        rollups: [
            {
                key: "components",
                path: [
                    {
                        graph_slug: "component",
                        alias: "item_visual_is_part_of_document",
                        direction: "incoming",
                    },
                ],
                aggregate: [{ op: "count" }],
                max_related: 500,
            },
        ],
    };
}

interface FakeResponse {
    ok: boolean;
    status: number;
    headers: { get(name: string): string | null };
    json: () => Promise<unknown>;
}

interface FetchCall {
    url: string;
    method: string;
    headers: Record<string, string>;
    body: string;
}

let calls: FetchCall[];
let configResponse: SummaryConfigResponse;
let saveResponse: SummaryConfigResponse;
let deleteResponse: SummaryConfigResponse;
let loadFails: boolean;
let relationsFail: boolean;
let saveFails: boolean;
let deleteFails: boolean;
let conflictOn: "PUT" | "DELETE" | null;
let readEtag: string;

function fakeResponse(
    payload: unknown,
    ok = true,
    status = 200,
    etag = '"v1"',
): FakeResponse {
    return {
        ok,
        status,
        headers: {
            get: (name: string) =>
                name.toLowerCase() === "etag" ? etag : null,
        },
        json: () => Promise.resolve(payload),
    };
}

function conflictResponse(): FakeResponse {
    return fakeResponse({ error: "changed" }, false, 412, '"v9"');
}

function installFetch(): void {
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string, init?: RequestInit): Promise<FakeResponse> => {
            const method = (init?.method ?? "GET").toUpperCase();
            calls.push({
                url,
                method,
                headers: (init?.headers ?? {}) as Record<string, string>,
                body: (init?.body ?? "") as string,
            });
            if (method === "DELETE") {
                if (conflictOn === "DELETE") {
                    return Promise.resolve(conflictResponse());
                }
                return Promise.resolve(
                    deleteFails
                        ? fakeResponse({}, false, 500)
                        : fakeResponse(deleteResponse, true, 200, '"v0"'),
                );
            }
            if (method === "PUT") {
                if (conflictOn === "PUT") {
                    return Promise.resolve(conflictResponse());
                }
                return Promise.resolve(
                    saveFails
                        ? fakeResponse({}, false, 500)
                        : fakeResponse(saveResponse, true, 200, '"v2"'),
                );
            }
            if (loadFails || (relationsFail && url === RELATIONS_URL)) {
                return Promise.resolve(fakeResponse({}, false, 403));
            }
            return Promise.resolve(
                fakeResponse(
                    url === RELATIONS_URL ? relations() : configResponse,
                    true,
                    200,
                    readEtag,
                ),
            );
        }),
    );
}

function putCalls(): FetchCall[] {
    return calls.filter((call) => call.method === "PUT");
}

async function mountForm() {
    const wrapper = mount(SummaryConfigForm, {
        props: { graphid: GRAPH_ID },
        global: { plugins: FORM_PLUGINS },
    });
    await flushPromises();
    await flushPromises();
    return wrapper;
}

function acceptConfirmation(): void {
    const buttons = document.body.querySelectorAll<HTMLElement>(
        '[data-testid="confirm-remove"]',
    );
    expect(buttons).toHaveLength(1);
    buttons[0].click();
}

beforeEach(() => {
    calls = [];
    loadFails = false;
    relationsFail = false;
    saveFails = false;
    deleteFails = false;
    conflictOn = null;
    readEtag = '"v1"';
    configResponse = {
        graphid: GRAPH_ID,
        config: storedConfig(),
        warnings: [],
        attached: true,
    };
    saveResponse = {
        graphid: GRAPH_ID,
        config: storedConfig(),
        warnings: [],
        attached: true,
    };
    deleteResponse = {
        graphid: GRAPH_ID,
        config: emptyConfig(),
        warnings: [],
        attached: false,
    };
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    installFetch();
});

describe("summary-config-api", () => {
    it("builds an empty configuration of the current schema version", () => {
        expect(emptyConfig()).toEqual({
            config_version: 1,
            fields: [],
            rollups: [],
        });
    });

    it("derives a field style from the datatype and falls back to text", () => {
        expect(defaultStyleFor("date")).toBe("date");
        expect(defaultStyleFor("reference")).toBe("chip");
        expect(defaultStyleFor("number")).toBe("number");
        expect(defaultStyleFor("resource-instance")).toBe("link");
        expect(defaultStyleFor("resource-instance-list")).toBe("link");
        expect(defaultStyleFor("file-list")).toBe("image");
        expect(defaultStyleFor("string")).toBe("text");
    });

    it("reads the CSRF cookie, and answers empty when there is none", () => {
        expect(csrfToken()).toBe("");
        document.cookie = "csrftoken=token-value";
        expect(csrfToken()).toBe("token-value");
    });

    it("reads the configuration from the summary-config route", async () => {
        const payload = await fetchConfig(GRAPH_ID);
        expect(calls[0].url).toBe(CONFIG_URL);
        expect(calls[0].method).toBe("GET");
        expect(payload.config).toEqual(storedConfig());
    });

    it("reads the relations from the relatable-nodes route", async () => {
        const payload = await fetchRelations(GRAPH_ID);
        expect(calls[0].url).toBe(RELATIONS_URL);
        expect(payload.graph.slug).toBe("document");
    });

    it("sends the configuration as a PUT carrying the CSRF token", async () => {
        document.cookie = "csrftoken=token-value";
        await saveConfig(GRAPH_ID, storedConfig(), null);
        const call = putCalls()[0];
        expect(call.url).toBe(CONFIG_URL);
        expect(call.headers["X-CSRFToken"]).toBe("token-value");
        expect(JSON.parse(call.body)).toEqual({ config: storedConfig() });
    });

    it("sends an empty CSRF header when the cookie is absent", async () => {
        await saveConfig(GRAPH_ID, storedConfig(), null);
        expect(putCalls()[0].headers["X-CSRFToken"]).toBe("");
    });

    it("rejects with the status of a refused response", async () => {
        loadFails = true;
        await expect(fetchConfig(GRAPH_ID)).rejects.toThrow("403");
    });

    it("lists the graphs a hop may name, current graph first", () => {
        expect(involvedGraphs(relations())).toEqual([
            { slug: "document", name: "Document" },
            { slug: "component", name: "Component" },
            { slug: "place", name: "Place" },
        ]);
        expect(involvedGraphs(null)).toEqual([]);
    });

    it("lists the relation aliases known for one graph", () => {
        expect(knownAliases(relations(), "document")).toEqual([
            "current_location",
        ]);
        expect(knownAliases(relations(), "component")).toEqual([
            "item_visual_is_part_of_document",
        ]);
        expect(knownAliases(relations(), "place")).toEqual([]);
        expect(knownAliases(null, "document")).toEqual([]);
    });

    it("seeds a hop from the first incoming relation", () => {
        expect(blankHop(relations())).toEqual({
            graph_slug: "component",
            alias: "item_visual_is_part_of_document",
            direction: "incoming",
        });
    });

    it("seeds a hop from an outgoing relation when nothing points here", () => {
        const withoutIncoming = { ...relations(), incoming: [] };
        expect(blankHop(withoutIncoming)).toEqual({
            graph_slug: "document",
            alias: "current_location",
            direction: "outgoing",
        });
    });

    it("seeds an empty hop for a model with no relation at all", () => {
        const isolated = { ...relations(), incoming: [], outgoing: [] };
        expect(blankHop(isolated)).toEqual({
            graph_slug: "document",
            alias: "",
            direction: "incoming",
        });
        expect(blankHop(null)).toEqual({
            graph_slug: "",
            alias: "",
            direction: "incoming",
        });
    });
});

describe("SummaryConfigForm", () => {
    it("loads the configuration and renders one row per field", async () => {
        const wrapper = await mountForm();
        expect(wrapper.findAllComponents(FieldRow)).toHaveLength(2);
        expect(wrapper.findAllComponents(RollupEditor)).toHaveLength(1);
        expect(calls.map((call) => call.url)).toContain(CONFIG_URL);
        expect(calls.map((call) => call.url)).toContain(RELATIONS_URL);
    });

    it("shows the warnings the endpoint reports on the stored configuration", async () => {
        configResponse.warnings = ["fields[2] (orphan): unknown style 'html'"];
        const wrapper = await mountForm();
        const shown = wrapper.findAll('[data-testid="config-warning"]');
        expect(shown).toHaveLength(1);
        expect(shown[0].text()).toContain("orphan");
    });

    it("shows an error when the configuration cannot be loaded", async () => {
        loadFails = true;
        const wrapper = await mountForm();
        expect(wrapper.find('[data-testid="config-error"]').exists()).toBe(
            true,
        );
        expect(wrapper.findAllComponents(FieldRow)).toHaveLength(0);
    });

    it("adds a field seeded with the style of its datatype", async () => {
        const wrapper = await mountForm();
        await wrapper.find('[data-testid="add-field"]').trigger("click");
        const rows = wrapper.findAllComponents(FieldRow);
        expect(rows).toHaveLength(3);
        expect(rows[2].props("alias")).toBe("label_of_name");
        expect(rows[2].props("fieldStyle")).toBe("text");
    });

    it("sends the edited configuration and shows what the server cleaned", async () => {
        const wrapper = await mountForm();
        await wrapper.find('[data-testid="add-field"]').trigger("click");
        wrapper
            .findAllComponents(FieldRow)[2]
            .vm.$emit("update:alias", "current_location");
        await flushPromises();

        saveResponse = {
            graphid: GRAPH_ID,
            config: storedConfig(),
            warnings: ["fields[2] (current_location): unknown style 'html'"],
            attached: true,
        };
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();

        const sent = JSON.parse(putCalls()[0].body) as {
            config: SummaryConfig;
        };
        expect(sent.config.fields).toHaveLength(3);
        expect(sent.config.fields[2]).toEqual({
            alias: "current_location",
            style: "link",
        });
        expect(wrapper.findAll('[data-testid="config-warning"]')).toHaveLength(
            1,
        );
        expect(wrapper.findAllComponents(FieldRow)).toHaveLength(2);
    });

    it("shows an error when the configuration cannot be saved", async () => {
        saveFails = true;
        const wrapper = await mountForm();
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();
        expect(wrapper.find('[data-testid="config-error"]').text()).toContain(
            "500",
        );
    });

    it("removes a field", async () => {
        const wrapper = await mountForm();
        wrapper.findAllComponents(FieldRow)[0].vm.$emit("remove");
        await flushPromises();
        const rows = wrapper.findAllComponents(FieldRow);
        expect(rows).toHaveLength(1);
        expect(rows[0].props("alias")).toBe("period_production");
    });

    it("moves a field down and back up", async () => {
        const wrapper = await mountForm();
        wrapper.findAllComponents(FieldRow)[0].vm.$emit("move-down");
        await flushPromises();
        expect(
            wrapper
                .findAllComponents(FieldRow)
                .map((row) => row.props("alias")),
        ).toEqual(["period_production", "label_of_name"]);

        wrapper.findAllComponents(FieldRow)[1].vm.$emit("move-up");
        await flushPromises();
        expect(
            wrapper
                .findAllComponents(FieldRow)
                .map((row) => row.props("alias")),
        ).toEqual(["label_of_name", "period_production"]);
    });

    it("keeps the element of a row that a reorder moves", async () => {
        const wrapper = await mountForm();
        const moved = wrapper.findAllComponents(FieldRow)[0].element;

        wrapper.findAllComponents(FieldRow)[0].vm.$emit("move-down");
        await flushPromises();

        const rows = wrapper.findAllComponents(FieldRow);
        expect(rows.map((row) => row.props("alias"))).toEqual([
            "period_production",
            "label_of_name",
        ]);
        expect(rows[1].element).toBe(moved);
    });

    it("keeps the identity of a row out of what it sends", async () => {
        const wrapper = await mountForm();
        await wrapper.find('[data-testid="add-field"]').trigger("click");
        await wrapper.find('[data-testid="add-rollup"]').trigger("click");
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();

        expect(putCalls()[0].body.includes("uid")).toBe(false);
    });

    it("ignores a move that would leave the list", async () => {
        const wrapper = await mountForm();
        wrapper.findAllComponents(FieldRow)[0].vm.$emit("move-up");
        wrapper.findAllComponents(FieldRow)[1].vm.$emit("move-down");
        await flushPromises();
        expect(
            wrapper
                .findAllComponents(FieldRow)
                .map((row) => row.props("alias")),
        ).toEqual(["label_of_name", "period_production"]);
    });

    it("carries the style, the labels and the value ceiling of a field", async () => {
        const wrapper = await mountForm();
        const row = wrapper.findAllComponents(FieldRow)[0];
        row.vm.$emit("update:field-style", "chip");
        row.vm.$emit("update:label-en", "Title");
        row.vm.$emit("update:label-fr", "Titre");
        row.vm.$emit("update:max-values", 4);
        await flushPromises();
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();

        const sent = JSON.parse(putCalls()[0].body) as {
            config: SummaryConfig;
        };
        expect(sent.config.fields[0]).toEqual({
            alias: "label_of_name",
            style: "chip",
            max_values: 4,
            label: { en: "Title", fr: "Titre" },
        });
    });

    it("drops a label the editor empties again", async () => {
        const wrapper = await mountForm();
        const row = wrapper.findAllComponents(FieldRow)[0];
        row.vm.$emit("update:label-en", "Title");
        await flushPromises();
        row.vm.$emit("update:label-en", "");
        await flushPromises();
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();

        const sent = JSON.parse(putCalls()[0].body) as {
            config: SummaryConfig;
        };
        expect(sent.config.fields[0]).toEqual({
            alias: "label_of_name",
            style: "text",
        });
    });

    it("drops the value ceiling when it is cleared", async () => {
        const wrapper = await mountForm();
        wrapper
            .findAllComponents(FieldRow)[1]
            .vm.$emit("update:max-values", null);
        await flushPromises();
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();

        const sent = JSON.parse(putCalls()[0].body) as {
            config: SummaryConfig;
        };
        expect(sent.config.fields[1]).toEqual({
            alias: "period_production",
            style: "chip",
        });
    });

    it("adds a rollup seeded with one hop, and removes it again", async () => {
        const wrapper = await mountForm();
        await wrapper.find('[data-testid="add-rollup"]').trigger("click");
        const editors = wrapper.findAllComponents(RollupEditor);
        expect(editors).toHaveLength(2);
        expect(editors[1].props("path")).toEqual([
            {
                graph_slug: "component",
                alias: "item_visual_is_part_of_document",
                direction: "incoming",
            },
        ]);

        editors[1].vm.$emit("remove");
        await flushPromises();
        expect(wrapper.findAllComponents(RollupEditor)).toHaveLength(1);
    });

    it("carries every edit a rollup editor reports", async () => {
        const wrapper = await mountForm();
        await wrapper.find('[data-testid="add-rollup"]').trigger("click");
        const editor = wrapper.findAllComponents(RollupEditor)[0];
        editor.vm.$emit("update:rollup-key", "analyses");
        editor.vm.$emit("update:label-en", "Analyses");
        editor.vm.$emit("update:label-fr", "Analyses");
        editor.vm.$emit("update:max-related", 200);
        editor.vm.$emit("update:path", [
            {
                graph_slug: "analysis",
                alias: "component_observed",
                direction: "incoming",
            },
        ]);
        editor.vm.$emit("update:aggregate", [
            { op: "count" },
            {
                op: "distinct",
                alias: "color_features",
                style: "chip",
                limit: 8,
            },
        ]);
        await flushPromises();
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();

        const sent = JSON.parse(putCalls()[0].body) as {
            config: SummaryConfig;
        };
        expect(sent.config.rollups[0]).toEqual({
            key: "analyses",
            label: { en: "Analyses", fr: "Analyses" },
            path: [
                {
                    graph_slug: "analysis",
                    alias: "component_observed",
                    direction: "incoming",
                },
            ],
            aggregate: [
                { op: "count" },
                {
                    op: "distinct",
                    alias: "color_features",
                    style: "chip",
                    limit: 8,
                },
            ],
            max_related: 200,
        });
    });

    it("words a rejection that is not an Error", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(() => Promise.reject("the connection dropped")),
        );
        const wrapper = await mountForm();
        expect(wrapper.find('[data-testid="config-error"]').text()).toContain(
            "the connection dropped",
        );
    });

    it("still adds an empty field and rollup when the model is unknown", async () => {
        loadFails = true;
        const wrapper = await mountForm();
        await wrapper.find('[data-testid="add-field"]').trigger("click");
        await wrapper.find('[data-testid="add-rollup"]').trigger("click");

        const row = wrapper.findAllComponents(FieldRow)[0];
        expect(row.props("alias")).toBe("");
        expect(row.props("fieldStyle")).toBe("text");
        expect(
            wrapper.findAllComponents(RollupEditor)[0].props("path"),
        ).toEqual([{ graph_slug: "", alias: "", direction: "incoming" }]);
    });

    it("waits on the two payloads before drawing the form", () => {
        const wrapper = mount(SummaryConfigForm, {
            props: { graphid: GRAPH_ID },
            global: { plugins: FORM_PLUGINS },
        });
        expect(wrapper.find('[data-testid="config-loading"]').exists()).toBe(
            true,
        );
    });

    it("says the function is not attached to the model yet", async () => {
        configResponse.attached = false;
        const wrapper = await mountForm();
        expect(wrapper.find('[data-testid="config-unattached"]').exists()).toBe(
            true,
        );
    });

    it("keeps the style when the alias picked is not one of the model's", async () => {
        const wrapper = await mountForm();
        wrapper
            .findAllComponents(FieldRow)[1]
            .vm.$emit("update:alias", "renamed_away");
        await flushPromises();
        const row = wrapper.findAllComponents(FieldRow)[1];
        expect(row.props("alias")).toBe("renamed_away");
        expect(row.props("fieldStyle")).toBe("chip");
    });

    it("drops a rollup label the editor empties again", async () => {
        const wrapper = await mountForm();
        const editor = wrapper.findAllComponents(RollupEditor)[0];
        editor.vm.$emit("update:label-fr", "Composants");
        await flushPromises();
        editor.vm.$emit("update:label-fr", "");
        await flushPromises();
        await wrapper.find('[data-testid="save-config"]').trigger("click");
        await flushPromises();

        const sent = JSON.parse(putCalls()[0].body) as {
            config: SummaryConfig;
        };
        expect(sent.config.rollups[0].label).toBeUndefined();
    });
});

describe("summary-config-api versioning", () => {
    it("returns the ETag the configuration was read with", async () => {
        const stored = await fetchConfig(GRAPH_ID);
        expect(stored.etag).toBe('"v1"');
    });

    it("sends If-Match with the ETag it was given", async () => {
        await saveConfig(GRAPH_ID, storedConfig(), '"v1"');
        expect(putCalls()[0].headers["If-Match"]).toBe('"v1"');
    });

    it("omits If-Match when no ETag is known", async () => {
        await saveConfig(GRAPH_ID, storedConfig(), null);
        expect(putCalls()[0].headers["If-Match"]).toBeUndefined();
    });

    it("rejects a conflicting write with a ConfigConflictError", async () => {
        conflictOn = "PUT";
        await expect(
            saveConfig(GRAPH_ID, storedConfig(), '"v0"'),
        ).rejects.toBeInstanceOf(ConfigConflictError);
    });

    it("removes the configuration with a DELETE carrying If-Match and the CSRF token", async () => {
        document.cookie = "csrftoken=token-value";
        const detached = await removeConfig(GRAPH_ID, '"v1"');
        const call = calls.find((each) => each.method === "DELETE");
        expect(call?.url).toBe(CONFIG_URL);
        expect(call?.headers["If-Match"]).toBe('"v1"');
        expect(call?.headers["X-CSRFToken"]).toBe("token-value");
        expect(detached.attached).toBe(false);
    });

    it("echoes a tag a compressing proxy weakened", async () => {
        readEtag = 'W/"v1"';
        const stored = await fetchConfig(GRAPH_ID);
        await saveConfig(GRAPH_ID, storedConfig(), stored.etag);
        expect(putCalls()[0].headers["If-Match"]).toBe('W/"v1"');
    });

    it("rejects a conflicting removal with a ConfigConflictError", async () => {
        conflictOn = "DELETE";
        await expect(removeConfig(GRAPH_ID, '"v0"')).rejects.toBeInstanceOf(
            ConfigConflictError,
        );
    });
});

describe("SummaryConfigForm removal", () => {
    it("sends the loaded ETag when saving", async () => {
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();
        expect(putCalls()[0].headers["If-Match"]).toBe('"v1"');
    });

    it("sends the ETag of its last save with the next one", async () => {
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();
        expect(putCalls()[1].headers["If-Match"]).toBe('"v2"');
    });

    it("offers the removal only for an attached model", async () => {
        configResponse = { ...configResponse, attached: false };
        const wrapper = await mountForm();
        expect(wrapper.find("[data-testid='remove-config']").exists()).toBe(
            false,
        );
    });

    it("asks for confirmation before removing", async () => {
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='remove-config']").trigger("click");
        await flushPromises();
        expect(calls.some((call) => call.method === "DELETE")).toBe(false);
        expect(document.body.textContent).toContain(
            "Remove the summary configuration of this model?",
        );
    });

    it("emits detached after a removal", async () => {
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='remove-config']").trigger("click");
        await flushPromises();
        acceptConfirmation();
        await flushPromises();
        expect(calls.some((call) => call.method === "DELETE")).toBe(true);
        expect(wrapper.emitted("detached")).toHaveLength(1);
        expect(
            calls.find((call) => call.method === "DELETE")?.headers["If-Match"],
        ).toBe('"v1"');
    });

    it("keeps the form attached and says so when the removal fails", async () => {
        deleteFails = true;
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='remove-config']").trigger("click");
        await flushPromises();
        acceptConfirmation();
        await flushPromises();
        expect(wrapper.find("[data-testid='config-error']").text()).toContain(
            "could not be removed",
        );
        expect(wrapper.emitted("detached")).toBeUndefined();
        expect(wrapper.find("[data-testid='remove-config']").exists()).toBe(
            true,
        );
        expect(wrapper.find("[data-testid='config-unattached']").exists()).toBe(
            false,
        );
    });

    it("explains a conflict and offers to reload", async () => {
        conflictOn = "PUT";
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();
        expect(wrapper.find("[data-testid='config-error']").text()).toContain(
            "Someone else changed this configuration",
        );
        readEtag = '"v9"';
        await wrapper.find("[data-testid='reload-config']").trigger("click");
        await flushPromises();
        expect(wrapper.find("[data-testid='config-error']").exists()).toBe(
            false,
        );

        conflictOn = null;
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();
        expect(putCalls().at(-1)?.headers["If-Match"]).toBe('"v9"');
    });

    it("explains a conflicting removal without emitting detached", async () => {
        conflictOn = "DELETE";
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='remove-config']").trigger("click");
        await flushPromises();
        acceptConfirmation();
        await flushPromises();
        expect(wrapper.find("[data-testid='config-error']").text()).toContain(
            "Someone else changed this configuration",
        );
        expect(wrapper.find("[data-testid='reload-config']").exists()).toBe(
            true,
        );
        expect(wrapper.emitted("detached")).toBeUndefined();
    });

    it("offers no write after a failed read", async () => {
        loadFails = true;
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='add-field']").trigger("click");
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();

        expect(
            wrapper.find("[data-testid='save-config']").attributes("disabled"),
        ).toBeDefined();
        expect(wrapper.find("[data-testid='remove-config']").exists()).toBe(
            false,
        );
        expect(wrapper.find("[data-testid='reload-config']").exists()).toBe(
            true,
        );
        expect(calls.every((call) => call.method === "GET")).toBe(true);
    });

    it("offers no write when only the relations cannot be read", async () => {
        relationsFail = true;
        const wrapper = await mountForm();
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();

        expect(
            wrapper.find("[data-testid='save-config']").attributes("disabled"),
        ).toBeDefined();
        expect(wrapper.find("[data-testid='remove-config']").exists()).toBe(
            false,
        );
        expect(wrapper.find("[data-testid='reload-config']").exists()).toBe(
            true,
        );
        expect(calls.every((call) => call.method === "GET")).toBe(true);
    });

    it("reads both payloads again when a failed read is reloaded", async () => {
        loadFails = true;
        const wrapper = await mountForm();
        const before = calls.length;
        await wrapper.find("[data-testid='reload-config']").trigger("click");
        await flushPromises();

        const reread = calls.slice(before).map((call) => call.url);
        expect(reread).toHaveLength(2);
        expect(reread).toEqual(
            expect.arrayContaining([CONFIG_URL, RELATIONS_URL]),
        );
    });

    it("a successful reload after a failed read offers the writes again", async () => {
        loadFails = true;
        const wrapper = await mountForm();
        loadFails = false;
        readEtag = '"v3"';
        await wrapper.find("[data-testid='reload-config']").trigger("click");
        await flushPromises();

        expect(
            wrapper.find("[data-testid='save-config']").attributes("disabled"),
        ).toBeUndefined();
        expect(wrapper.find("[data-testid='remove-config']").exists()).toBe(
            true,
        );
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();
        expect(putCalls()[0].headers["If-Match"]).toBe('"v3"');
    });

    it("brings a conflict into view from the bottom of a long form", async () => {
        conflictOn = "PUT";
        const wrapper = await mountForm();
        wrapper.element.scrollTop = 500;
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();

        expect(wrapper.element.scrollTop).toBe(0);
        expect(wrapper.find("[data-testid='reload-config']").exists()).toBe(
            true,
        );
    });

    it("brings the saved notice into view from the bottom of a long form", async () => {
        const wrapper = await mountForm();
        wrapper.element.scrollTop = 500;
        await wrapper.find("[data-testid='save-config']").trigger("click");
        await flushPromises();

        expect(wrapper.element.scrollTop).toBe(0);
        expect(wrapper.find("[data-testid='config-saved']").exists()).toBe(
            true,
        );
    });
});

describe("FieldRow", () => {
    function mountRow(alias = "label_of_name") {
        return mount(FieldRow, {
            props: {
                alias,
                fieldStyle: "text" as const,
                labelEn: "",
                labelFr: "",
                maxValues: null,
                aliasOptions: relations().fields,
                canMoveUp: true,
                canMoveDown: true,
            },
            global: { plugins: [[PrimeVue, { unstyled: true }]] },
        });
    }

    it("flags an alias the model no longer carries", () => {
        expect(mountRow("renamed_away").find(".unknown-alias").exists()).toBe(
            true,
        );
        expect(mountRow().find(".unknown-alias").exists()).toBe(false);
    });

    it("reports removal and reordering to its parent", async () => {
        const row = mountRow();
        await row.find('[data-testid="remove-field"]').trigger("click");
        await row.find('[data-testid="move-field-up"]').trigger("click");
        await row.find('[data-testid="move-field-down"]').trigger("click");
        expect(row.emitted("remove")).toHaveLength(1);
        expect(row.emitted("move-up")).toHaveLength(1);
        expect(row.emitted("move-down")).toHaveLength(1);
    });

    it("reports what each of its controls changes", async () => {
        const row = mountRow();
        row.findComponent<ComponentPublicInstance>(
            '[data-testid="field-alias"]',
        ).vm.$emit("update:modelValue", "period_production");
        row.findComponent<ComponentPublicInstance>(
            '[data-testid="field-style"]',
        ).vm.$emit("update:modelValue", "chip");
        row.findComponent<ComponentPublicInstance>(
            '[data-testid="field-label-en"]',
        ).vm.$emit("update:modelValue", null);
        row.findComponent<ComponentPublicInstance>(
            '[data-testid="field-label-fr"]',
        ).vm.$emit("update:modelValue", "Titre");
        row.findComponent<ComponentPublicInstance>(
            '[data-testid="field-max-values"]',
        ).vm.$emit("update:modelValue", 3);
        await flushPromises();

        expect(row.emitted("update:alias")?.[0]).toEqual(["period_production"]);
        expect(row.emitted("update:field-style")?.[0]).toEqual(["chip"]);
        expect(row.emitted("update:label-en")?.[0]).toEqual([""]);
        expect(row.emitted("update:label-fr")?.[0]).toEqual(["Titre"]);

        row.findComponent<ComponentPublicInstance>(
            '[data-testid="field-label-en"]',
        ).vm.$emit("update:modelValue", "Title");
        row.findComponent<ComponentPublicInstance>(
            '[data-testid="field-label-fr"]',
        ).vm.$emit("update:modelValue", null);
        await flushPromises();
        expect(row.emitted("update:label-en")?.[1]).toEqual(["Title"]);
        expect(row.emitted("update:label-fr")?.[1]).toEqual([""]);
        expect(row.emitted("update:max-values")?.[0]).toEqual([3]);
    });
});

describe("RollupEditor", () => {
    function mountEditor(path = storedConfig().rollups[0].path) {
        return mount(RollupEditor, {
            props: {
                rollupKey: "components",
                labelEn: "",
                labelFr: "",
                path,
                aggregate: [{ op: "count" as const }],
                maxRelated: 500,
                relations: relations(),
            },
            global: { plugins: [[PrimeVue, { unstyled: true }]] },
        });
    }

    it("appends a second hop", async () => {
        const editor = mountEditor();
        await editor.find('[data-testid="add-hop"]').trigger("click");
        expect(editor.emitted("update:path")?.[0][0]).toHaveLength(2);
    });

    it("refuses a third hop", async () => {
        const editor = mountEditor([
            {
                graph_slug: "component",
                alias: "item_visual_is_part_of_document",
                direction: "incoming",
            },
            {
                graph_slug: "analysis",
                alias: "component_observed",
                direction: "incoming",
            },
        ]);
        const button = editor.find('[data-testid="add-hop"]');
        expect(button.attributes("disabled")).toBeDefined();
        await button.trigger("click");
        expect(editor.emitted("update:path")).toBeUndefined();
    });

    it("removes a hop only while more than one remains", async () => {
        const editor = mountEditor([
            {
                graph_slug: "component",
                alias: "item_visual_is_part_of_document",
                direction: "incoming",
            },
            {
                graph_slug: "analysis",
                alias: "component_observed",
                direction: "incoming",
            },
        ]);
        await editor.findAll('[data-testid="remove-hop"]')[1].trigger("click");
        expect(editor.emitted("update:path")?.[0][0]).toHaveLength(1);
        expect(
            mountEditor().findAll('[data-testid="remove-hop"]'),
        ).toHaveLength(0);
    });

    it("adds and drops the distinct aggregate", async () => {
        const editor = mountEditor();
        await editor.find('[data-testid="toggle-distinct"]').trigger("click");
        expect(editor.emitted("update:aggregate")?.[0][0]).toEqual([
            { op: "count" },
            {
                op: "distinct",
                alias: "color_features",
                style: "chip",
                limit: 5,
            },
        ]);

        const withDistinct = mount(RollupEditor, {
            props: {
                rollupKey: "components",
                labelEn: "",
                labelFr: "",
                path: storedConfig().rollups[0].path,
                aggregate: [
                    { op: "count" as const },
                    {
                        op: "distinct" as const,
                        alias: "color_features",
                        style: "chip" as const,
                        limit: 5,
                    },
                ],
                maxRelated: 500,
                relations: relations(),
            },
            global: { plugins: [[PrimeVue, { unstyled: true }]] },
        });
        await withDistinct
            .find('[data-testid="toggle-distinct"]')
            .trigger("click");
        expect(withDistinct.emitted("update:aggregate")?.[0][0]).toEqual([
            { op: "count" },
        ]);
    });

    it("reports the rest of its edits", async () => {
        const editor = mountEditor();
        await editor.find('[data-testid="remove-rollup"]').trigger("click");
        expect(editor.emitted("remove")).toHaveLength(1);
    });

    it("rewrites the hop whose control changed", async () => {
        const editor = mountEditor();
        editor
            .findComponent<ComponentPublicInstance>('[data-testid="hop-graph"]')
            .vm.$emit("update:modelValue", "place");
        editor
            .findComponent<ComponentPublicInstance>('[data-testid="hop-alias"]')
            .vm.$emit("update:modelValue", null);
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="hop-direction"]',
            )
            .vm.$emit("update:modelValue", "outgoing");
        await flushPromises();

        const reported = editor.emitted("update:path") as SummaryHop[][][];
        expect(reported[0][0]).toEqual([
            {
                graph_slug: "place",
                alias: "item_visual_is_part_of_document",
                direction: "incoming",
            },
        ]);
        expect(reported[1][0][0].alias).toBe("");
        expect(reported[2][0][0].direction).toBe("outgoing");
    });

    it("reports the key, the labels and the ceiling its inputs change", async () => {
        const editor = mountEditor();
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="rollup-key"]',
            )
            .vm.$emit("update:modelValue", "analyses");
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="rollup-label-en"]',
            )
            .vm.$emit("update:modelValue", "Analyses");
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="rollup-label-fr"]',
            )
            .vm.$emit("update:modelValue", null);
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="rollup-max-related"]',
            )
            .vm.$emit("update:modelValue", null);
        await flushPromises();

        expect(editor.emitted("update:rollup-key")?.[0]).toEqual(["analyses"]);
        expect(editor.emitted("update:label-en")?.[0]).toEqual(["Analyses"]);
        expect(editor.emitted("update:label-fr")?.[0]).toEqual([""]);
        expect(editor.emitted("update:max-related")?.[0]).toEqual([500]);

        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="rollup-key"]',
            )
            .vm.$emit("update:modelValue", null);
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="rollup-label-en"]',
            )
            .vm.$emit("update:modelValue", null);
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="rollup-max-related"]',
            )
            .vm.$emit("update:modelValue", 200);
        await flushPromises();
        expect(editor.emitted("update:rollup-key")?.[1]).toEqual([""]);
        expect(editor.emitted("update:label-en")?.[1]).toEqual([""]);
        expect(editor.emitted("update:max-related")?.[1]).toEqual([200]);
    });

    it("rewrites the alias and the ceiling of the distinct aggregate", async () => {
        const editor = mount(RollupEditor, {
            props: {
                rollupKey: "components",
                labelEn: "",
                labelFr: "",
                path: storedConfig().rollups[0].path,
                aggregate: [
                    { op: "count" as const },
                    {
                        op: "distinct" as const,
                        alias: "color_features",
                        style: "chip" as const,
                        limit: 5,
                    },
                ],
                maxRelated: 500,
                relations: relations(),
            },
            global: { plugins: [[PrimeVue, { unstyled: true }]] },
        });
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="distinct-alias"]',
            )
            .vm.$emit("update:modelValue", null);
        editor
            .findComponent<ComponentPublicInstance>(
                '[data-testid="distinct-limit"]',
            )
            .vm.$emit("update:modelValue", 7);
        await flushPromises();

        const reported = editor.emitted(
            "update:aggregate",
        ) as SummaryAggregate[][][];
        expect(reported[0][0][1].alias).toBe("");
        expect(reported[1][0][1].limit).toBe(7);
    });

    it("seeds a distinct aggregate with no alias when none is aggregatable", async () => {
        const editor = mountEditor([
            {
                graph_slug: "unknown_model",
                alias: "whatever",
                direction: "incoming",
            },
        ]);
        await editor.find('[data-testid="toggle-distinct"]').trigger("click");
        const reported = editor.emitted(
            "update:aggregate",
        ) as SummaryAggregate[][][];
        expect(reported[0][0][1].alias).toBe("");
    });
});
