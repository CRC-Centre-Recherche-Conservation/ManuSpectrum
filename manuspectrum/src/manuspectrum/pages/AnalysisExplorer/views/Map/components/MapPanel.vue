<script setup lang="ts">
import {
    computed,
    nextTick,
    onMounted,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import BulkStatusLine from "@/manuspectrum/pages/AnalysisExplorer/components/BulkStatusLine.vue";
import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";
import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import SelectAllCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectAllCheckbox.vue";
import SelectionCapacityNotice from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionCapacityNotice.vue";
import SelectionCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionCheckbox.vue";
import TechniqueTag from "@/manuspectrum/pages/AnalysisExplorer/components/TechniqueTag.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    documentHref,
    snapshotOf,
} from "@/manuspectrum/pages/AnalysisExplorer/store/url.ts";
import { focusHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import { intervalOf } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/aoristic.ts";
import { formatEventDate } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/event-format.ts";
import {
    absentTracked,
    panelContent,
    subjectEvents,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/panel-groups.ts";
import { isLow } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

import type {
    CertaintyScale,
    EventMaterial,
    Label,
    MapEvent,
    MapMaterial,
    MapPlace,
    TechniqueMark,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type {
    PanelDocument,
    PanelSubject,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/panel-groups.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

interface Attested {
    uri: string;
    label: Label;
    swatch: string | null;
    slot: number | null;
    /** Every attestation here is « use with caution » or « uncertain ». */
    pale: boolean;
    reliability: string | null;
    documents: number;
    components: number;
}

interface ComponentGroup {
    /** Unique in the panel: the document id, then the Component id or « own ». */
    key: string;
    title: string;
    lang: string | undefined;
    events: MapEvent[];
    analyses: string[];
    keys: string[];
}

interface DocumentView {
    document: PanelDocument;
    groups: ComponentGroup[];
    keys: string[];
    components: number;
    dates: string;
    techniques: TechniqueMark[];
}

const DOCUMENTS_SHOWN = 5;
const DOCUMENTS_STEP = 10;
const ANALYSES_SHOWN = 5;
const ANALYSES_STEP = 20;
const EVENTS_SHOWN = 3;
const COMPONENTS_SHOWN = 4;
const MATERIALS_SHOWN = 8;
const TECHNIQUES_SUMMARY = 3;
const GEONAMES = /^\d+$/;
const WIKIDATA = /^Q\d+$/;
const OWN = "own";

/**
 * What the map, the timeline or the place list opened: a place, a period,
 * a document, a material, or the events without a mapped place, over the
 * brushed kept events. The head names it (a place with its Draft badge,
 * « Attributed place » for an area or a place reached through its parent,
 * its GeoNames and Wikidata records); then the materials attested here,
 * followed first, a sentence for each followed material absent here, and
 * the analyses by document and Component with the Selection's select-all,
 * capacity notice and bulk line. The heading takes the focus when the panel
 * opens or changes subject; Escape and « Close » emit `close`; a period's
 * « Show only this period on the map » emits `brush`.
 *
 * Long subjects stay short: the first 8 materials, the first 5 documents
 * (10 more per click), documents folded unless the subject has one with at
 * most 10 analyses (a folded body is not mounted), per document the first
 * 4 Components (the others on one click), per Component the first
 * 3 events and the first 5 analyses (20 more per click), and past the
 * Selection's capacity a note that sends to the document in Corpus. What is
 * unfolded resets when the subject changes.
 */
const props = defineProps<{
    subject: PanelSubject;
    events: MapEvent[];
    places: Record<string, MapPlace>;
    analysisNames: Record<string, Label>;
    analysisTechniques: Record<string, TechniqueMark>;
    tracked: TrackedMaterial[];
    low: Set<string>;
    materials: Record<string, MapMaterial>;
    certainty: CertaintyScale;
}>();
const emit = defineEmits<{ close: []; brush: [range: [number, number]] }>();

const store = useExplorerStore();
const toggle = useSelectionToggle();
const gettext = useGettext();
const { $gettext, $ngettext, interpolate } = gettext;
const { eventTypeLabel, placeSourceLabel } = useVocabulary();
const noticeId = useId();
const heading = useTemplateRef<HTMLElement>("heading");
const bodyId = useId();

const documentsShown = ref(DOCUMENTS_SHOWN);
const allMaterials = ref(false);
/** Documents the reader folded or unfolded, by id; the others follow `openByDefault`. */
const toggled = ref(new Map<string, boolean>());
/** Analyses shown per Component group past the first `ANALYSES_SHOWN`. */
const analysesShown = ref(new Map<string, number>());
const eventsOpen = ref(new Set<string>());
/** Component groups shown per document past the first `COMPONENTS_SHOWN`. */
const groupsShown = ref(new Map<string, number>());

const shown = computed(() =>
    subjectEvents(props.events, props.places, props.subject),
);
const content = computed(() => panelContent(shown.value));
const keys = computed(() => content.value.analyses.map(analysisKey));
const hints = computed(
    () =>
        new Map<string, SelectionHint>(
            content.value.analyses.map((id) => [
                analysisKey(id),
                { title: analysisName(id), kind: $gettext("analysis") },
            ]),
        ),
);
const absent = computed(() => absentTracked(shown.value, props.tracked));
const place = computed<MapPlace | null>(() =>
    props.subject.kind === "place"
        ? props.places[props.subject.id] ?? null
        : null,
);
const attributed = computed(() => {
    const found = place.value;
    if (!found) return false;
    return (
        found.geometryKind === "area" ||
        (shown.value.length > 0 &&
            shown.value.every((event) => event.placeSource === "parent"))
    );
});
const parentName = computed(() => {
    const parent = place.value?.parent;
    return parent ? props.places[parent]?.name ?? null : null;
});
const title = computed<Label>(() => {
    const subject = props.subject;
    switch (subject.kind) {
        case "place":
            return (
                place.value?.name ?? {
                    value: $gettext("Unknown place"),
                    lang: "",
                }
            );
        case "period":
            return {
                value: interpolate(
                    $gettext("%{start}–%{end}"),
                    { start: subject.from, end: subject.to },
                    true,
                ),
                lang: "",
            };
        case "document":
            return (
                shown.value[0]?.document.name ?? {
                    value: $gettext("Document"),
                    lang: "",
                }
            );
        case "material":
            return (
                props.materials[subject.uri]?.label ??
                shown.value
                    .flatMap((event) => event.materials)
                    .find((material) => material.id === subject.uri)?.name ?? {
                    value: subject.uri,
                    lang: "",
                }
            );
        case "unplaced":
            return {
                value: $gettext("Events without a mapped place"),
                lang: "",
            };
    }
    return { value: "", lang: "" };
});
const kind = computed(() => {
    switch (props.subject.kind) {
        case "place":
            return attributed.value
                ? $gettext("Attributed place")
                : $gettext("Place");
        case "period":
            return $gettext("Period");
        case "document":
            return $gettext("Document");
        case "material":
            return $gettext("Material");
        case "unplaced":
            return "";
    }
    return "";
});
const authorities = computed(() => {
    const found = place.value;
    if (!found) return [];
    const links: { key: string; href: string; text: string; name: string }[] =
        [];
    const { geonames, wikidata } = found.authorities;
    if (geonames && GEONAMES.test(geonames)) {
        links.push({
            key: "geonames",
            href: `https://www.geonames.org/${geonames}`,
            text: "GeoNames",
            name: interpolate(
                $gettext("GeoNames record of %{place} (new tab)"),
                { place: found.name.value },
                true,
            ),
        });
    }
    if (wikidata && WIKIDATA.test(wikidata)) {
        links.push({
            key: "wikidata",
            href: `https://www.wikidata.org/wiki/${wikidata}`,
            text: "Wikidata",
            name: interpolate(
                $gettext("Wikidata record of %{place} (new tab)"),
                { place: found.name.value },
                true,
            ),
        });
    }
    return links;
});
const documentsChip = computed(() =>
    interpolate(
        $ngettext(
            "%{n} analysed document",
            "%{n} analysed documents",
            content.value.documents.length,
        ),
        { n: content.value.documents.length },
        true,
    ),
);
const countsLine = computed(() =>
    interpolate(
        $gettext("%{documents} · %{components} · %{analyses}"),
        {
            documents: interpolate(
                $ngettext(
                    "%{n} document",
                    "%{n} documents",
                    content.value.documents.length,
                ),
                { n: content.value.documents.length },
                true,
            ),
            components: interpolate(
                $ngettext(
                    "%{n} Component",
                    "%{n} Components",
                    content.value.components,
                ),
                { n: content.value.components },
                true,
            ),
            analyses: interpolate(
                $ngettext("%{n} analysis", "%{n} analyses", keys.value.length),
                { n: keys.value.length },
                true,
            ),
        },
        true,
    ),
);
const pageName = computed(() =>
    interpolate(
        $gettext("Add the analyses of %{subject} to the Selection"),
        { subject: title.value.value },
        true,
    ),
);
const attested = computed<Attested[]>(() => {
    const found = new Map<
        string,
        {
            label: Label;
            documents: Set<string>;
            components: Set<string>;
            materials: EventMaterial[];
        }
    >();
    for (const event of shown.value) {
        for (const material of event.materials) {
            let entry = found.get(material.id);
            if (!entry) {
                entry = {
                    label: material.name,
                    documents: new Set(),
                    components: new Set(),
                    materials: [],
                };
                found.set(material.id, entry);
            }
            entry.documents.add(event.document.id);
            if (event.component) entry.components.add(event.component.id);
            entry.materials.push(material);
        }
    }
    return [...found]
        .map(([uri, entry]) => ({
            uri,
            label: props.materials[uri]?.label ?? entry.label,
            swatch: props.materials[uri]?.swatch ?? null,
            slot: slotOf(uri),
            pale: entry.materials.every((m) => isLow(m, props.low)),
            reliability: bestReliability(entry.materials),
            documents: entry.documents.size,
            components: entry.components.size,
        }))
        .sort(
            (a, b) =>
                (a.slot ?? Infinity) - (b.slot ?? Infinity) ||
                b.components - a.components ||
                a.label.value.localeCompare(b.label.value),
        );
});
const shownAttested = computed(() =>
    allMaterials.value
        ? attested.value
        : attested.value.slice(0, MATERIALS_SHOWN),
);
const hiddenMaterials = computed(
    () => attested.value.length - shownAttested.value.length,
);
const moreMaterialsText = computed(() =>
    interpolate(
        $ngettext(
            "Show %{n} more material",
            "Show %{n} more materials",
            hiddenMaterials.value,
        ),
        { n: hiddenMaterials.value },
        true,
    ),
);
const documents = computed<DocumentView[]>(() =>
    content.value.documents
        .slice(0, documentsShown.value)
        .map((document) => documentView(document)),
);
const hiddenDocuments = computed(
    () => content.value.documents.length - documents.value.length,
);
const openByDefault = computed(
    () =>
        content.value.documents.length === 1 &&
        content.value.analyses.length <= ANALYSES_SHOWN * 2,
);
const moreDocumentsText = computed(() =>
    interpolate(
        $ngettext(
            "+ %{n} other document",
            "+ %{n} other documents",
            hiddenDocuments.value,
        ),
        { n: hiddenDocuments.value },
        true,
    ),
);
const compareText = computed(() =>
    interpolate($gettext("Compare (%{n})"), { n: store.basket.length }, true),
);
const canCompare = computed(() => store.basket.length > 0);

watch(
    () => props.subject,
    async () => {
        documentsShown.value = DOCUMENTS_SHOWN;
        allMaterials.value = false;
        toggled.value = new Map();
        analysesShown.value = new Map();
        eventsOpen.value = new Set();
        groupsShown.value = new Map();
        await nextTick();
        heading.value?.focus();
    },
);

onMounted(() => {
    heading.value?.focus();
});

function analysisName(id: string): Label {
    return props.analysisNames[id] ?? { value: id, lang: "" };
}

function slotOf(uri: string): number | null {
    return props.tracked.find((entry) => entry.uri === uri)?.slot ?? null;
}

function levelOf(id: string | null): { label: Label; rank: number } | null {
    if (id === null) return null;
    return props.certainty.levels.find((level) => level.id === id) ?? null;
}

function bestReliability(materials: readonly EventMaterial[]): string | null {
    const levels = materials
        .map((material) => levelOf(material.reliability))
        .filter((level) => level !== null);
    if (levels.length === 0) return null;
    return levels.reduce((best, level) =>
        level.rank < best.rank ? level : best,
    ).label.value;
}

function attestedCounts(row: Attested): string {
    return interpolate(
        $gettext("%{documents} doc. · %{components} comp."),
        { documents: row.documents, components: row.components },
        true,
    );
}

function absenceText(uri: string): string {
    const material =
        props.materials[uri]?.label.value ??
        props.events
            .flatMap((event) => event.materials)
            .find((entry) => entry.id === uri)?.name.value ??
        uri;
    const count = content.value.documents.length;
    return interpolate(
        $ngettext(
            "%{material} not attested among the %{n} document analysed here. This does not mean it was not used.",
            "%{material} not attested among the %{n} documents analysed here. This does not mean it was not used.",
            count,
        ),
        { material, n: count },
        true,
    );
}

function analysesOf(events: readonly MapEvent[]): string[] {
    const ids = new Set<string>();
    for (const event of events) {
        for (const id of event.analyses) ids.add(id);
    }
    return [...ids];
}

function group(
    key: string,
    title: string,
    lang: string | undefined,
    events: MapEvent[],
): ComponentGroup {
    const analyses = analysesOf(events);
    return {
        key,
        title,
        lang,
        events,
        analyses,
        keys: analyses.map(analysisKey),
    };
}

function groupsOf(document: PanelDocument): ComponentGroup[] {
    const groups: ComponentGroup[] = [];
    if (document.own.length > 0) {
        groups.push(
            group(
                `${document.id}:${OWN}`,
                $gettext("Document itself"),
                undefined,
                document.own,
            ),
        );
    }
    for (const component of document.components) {
        groups.push(
            group(
                `${document.id}:${component.id}`,
                component.name.value,
                component.name.lang || undefined,
                component.events,
            ),
        );
    }
    return groups;
}

/** The most used techniques of `ids`, at most `TECHNIQUES_SUMMARY`, by code on a tie. */
function techniqueSummary(ids: readonly string[]): TechniqueMark[] {
    const counts = new Map<string, { mark: TechniqueMark; count: number }>();
    for (const id of ids) {
        const mark = props.analysisTechniques[id];
        if (!mark) continue;
        const entry = counts.get(mark.code);
        if (entry) entry.count += 1;
        else counts.set(mark.code, { mark, count: 1 });
    }
    return [...counts.values()]
        .sort(
            (a, b) =>
                b.count - a.count || a.mark.code.localeCompare(b.mark.code),
        )
        .slice(0, TECHNIQUES_SUMMARY)
        .map((entry) => entry.mark);
}

function documentView(document: PanelDocument): DocumentView {
    const analyses = analysesOf([
        ...document.own,
        ...document.components.flatMap((component) => component.events),
    ]);
    return {
        document,
        groups: groupsOf(document),
        keys: analyses.map(analysisKey),
        components: document.components.length,
        dates: documentDates(document),
        techniques: techniqueSummary(analyses),
    };
}

function isOpen(id: string): boolean {
    return toggled.value.get(id) ?? openByDefault.value;
}

function toggleDocument(id: string): void {
    const next = new Map(toggled.value);
    next.set(id, !isOpen(id));
    toggled.value = next;
}

function documentCounts(view: DocumentView): string {
    return interpolate(
        $gettext("%{components} · %{analyses}"),
        {
            components: interpolate(
                $ngettext("%{n} Component", "%{n} Components", view.components),
                { n: view.components },
                true,
            ),
            analyses: interpolate(
                $ngettext("%{n} analysis", "%{n} analyses", view.keys.length),
                { n: view.keys.length },
                true,
            ),
        },
        true,
    );
}

function shownGroups(view: DocumentView): ComponentGroup[] {
    return view.groups.slice(
        0,
        groupsShown.value.get(view.document.id) ?? COMPONENTS_SHOWN,
    );
}

function hiddenGroups(view: DocumentView): number {
    return view.groups.length - shownGroups(view).length;
}

function showMoreGroups(view: DocumentView): void {
    const next = new Map(groupsShown.value);
    next.set(view.document.id, view.groups.length);
    groupsShown.value = next;
}

function moreGroupsText(view: DocumentView): string {
    const n = hiddenGroups(view);
    return interpolate(
        $ngettext("Show %{n} more Component", "Show %{n} more Components", n),
        { n },
        true,
    );
}

function shownAnalyses(entry: ComponentGroup): string[] {
    return entry.analyses.slice(
        0,
        analysesShown.value.get(entry.key) ?? ANALYSES_SHOWN,
    );
}

function hiddenAnalyses(entry: ComponentGroup): number {
    return entry.analyses.length - shownAnalyses(entry).length;
}

function showMoreAnalyses(entry: ComponentGroup): void {
    const next = new Map(analysesShown.value);
    next.set(entry.key, shownAnalyses(entry).length + ANALYSES_STEP);
    analysesShown.value = next;
}

function moreAnalysesText(entry: ComponentGroup): string {
    const n = Math.min(ANALYSES_STEP, hiddenAnalyses(entry));
    return interpolate(
        $ngettext("Show %{n} more analysis", "Show %{n} more analyses", n),
        { n },
        true,
    );
}

function overCapacity(entry: ComponentGroup): boolean {
    return entry.analyses.length > BASKET_LIMIT;
}

function capacityText(entry: ComponentGroup): string {
    return interpolate(
        $gettext(
            "%{n} analyses here: open the document in Corpus to filter them by technique.",
        ),
        { n: entry.analyses.length },
        true,
    );
}

function shownEvents(entry: ComponentGroup): MapEvent[] {
    return eventsOpen.value.has(entry.key)
        ? entry.events
        : entry.events.slice(0, EVENTS_SHOWN);
}

function hiddenEvents(entry: ComponentGroup): number {
    return entry.events.length - shownEvents(entry).length;
}

function showAllEvents(entry: ComponentGroup): void {
    eventsOpen.value = new Set([...eventsOpen.value, entry.key]);
}

function moreEventsText(entry: ComponentGroup): string {
    const n = hiddenEvents(entry);
    return interpolate(
        $ngettext("+ %{n} event", "+ %{n} events", n),
        { n },
        true,
    );
}

function showMoreDocuments(): void {
    documentsShown.value += DOCUMENTS_STEP;
}

function techniqueOf(id: string): TechniqueMark | null {
    return props.analysisTechniques[id] ?? null;
}

function brushPeriod(): void {
    const subject = props.subject;
    if (subject.kind === "period") emit("brush", [subject.from, subject.to]);
}

function documentDates(document: PanelDocument): string {
    const intervals = [
        ...document.own,
        ...document.components.flatMap((component) => component.events),
    ].flatMap((event) => {
        const interval = intervalOf(event.date);
        return interval
            ? [{ interval, approximate: event.date.approximate }]
            : [];
    });
    if (intervals.length === 0) return "";
    return formatEventDate(
        {
            start: Math.min(...intervals.map((entry) => entry.interval[0])),
            end: Math.max(...intervals.map((entry) => entry.interval[1])),
            approximate: intervals.some((entry) => entry.approximate),
        },
        $gettext,
        interpolate,
    );
}

function selectName(subject: string): string {
    return interpolate(
        $gettext("Select the analyses of %{subject}"),
        { subject },
        true,
    );
}

/** Whether `event` is a production whose Component (or document) has no modification in this panel. */
function placedOnProduction(event: MapEvent): boolean {
    if (event.type !== "production" || event.materials.length === 0) {
        return false;
    }
    return !shown.value.some(
        (other) =>
            other.type === "modification" &&
            other.document.id === event.document.id &&
            (other.component?.id ?? null) === (event.component?.id ?? null),
    );
}

function dateOf(event: MapEvent): string {
    return formatEventDate(event.date, $gettext, interpolate);
}

function materialHue(material: EventMaterial): Record<string, string> {
    const slot = slotOf(material.id);
    const swatch = props.materials[material.id]?.swatch;
    return {
        ...(slot === null ? {} : { "--h": focusHue(slot) }),
        ...(swatch ? { "--swatch": swatch } : {}),
    };
}

function reliabilityOf(material: EventMaterial): string {
    return levelOf(material.reliability)?.label.value ?? "";
}

function hintOf(id: string): SelectionHint | undefined {
    return hints.value.get(analysisKey(id));
}

function openDocument(id: string): void {
    store.openDocument(id);
}

function compare(): void {
    if (canCompare.value) store.setView("compare");
}
</script>

<template>
    <article
        class="map-panel"
        @keydown.esc="emit('close')"
    >
        <header class="card-head">
            <h2
                ref="heading"
                class="name"
                tabindex="-1"
                :lang="title.lang || undefined"
            >
                <span>{{ title.value }}</span>
            </h2>
            <IconButton
                class="close-icon"
                icon="times"
                :label="$gettext('Close the panel')"
                :description="$gettext('Escape')"
                @click="emit('close')"
            />
            <p
                v-if="kind || parentName || place?.unpublished"
                class="meta"
            >
                <span v-if="kind">{{ kind }}</span>
                <button
                    v-if="props.subject.kind === 'period'"
                    type="button"
                    class="pill brush-period"
                    @click="brushPeriod"
                >
                    <span>{{
                        $gettext("Show only this period on the map")
                    }}</span>
                </button>
                <span
                    v-if="parentName"
                    :lang="parentName.lang || undefined"
                    >{{ parentName.value }}</span
                >
                <span
                    v-if="place?.unpublished"
                    class="badge"
                    >{{ $gettext("Draft") }}</span
                >
            </p>
        </header>

        <div class="chips">
            <span class="chip">{{ documentsChip }}</span>
            <a
                v-for="link in authorities"
                :key="link.key"
                class="chip authority"
                target="_blank"
                rel="noopener"
                :href="link.href"
                :aria-label="link.name"
            >
                <span>{{ link.text }}</span>
                <span aria-hidden="true">{{ " ↗" }}</span>
            </a>
        </div>
        <p class="counts-line">
            <span>{{ countsLine }}</span>
        </p>

        <section
            v-if="attested.length > 0"
            class="attested"
        >
            <h3 class="kicker">{{ $gettext("Materials attested here") }}</h3>
            <ul>
                <li
                    v-for="row in shownAttested"
                    :key="row.uri"
                    :class="{ pale: row.pale }"
                    :style="
                        row.slot === null ? {} : { '--h': focusHue(row.slot) }
                    "
                >
                    <span
                        class="swatch"
                        :class="{ unknown: !row.swatch }"
                        aria-hidden="true"
                        :style="row.swatch ? { '--swatch': row.swatch } : {}"
                    ></span>
                    <template v-if="row.slot !== null">
                        <span
                            v-if="row.pale"
                            class="hollow-dot"
                            aria-hidden="true"
                            >{{ row.slot }}</span
                        >
                        <FocusSlotDot
                            v-else
                            size="medium"
                            :number="row.slot"
                        />
                    </template>
                    <span
                        v-else
                        class="spacer"
                        aria-hidden="true"
                    ></span>
                    <span
                        class="label"
                        :lang="row.label.lang || undefined"
                        >{{ row.label.value }}</span
                    >
                    <span class="meta">
                        <span class="facts">
                            <span
                                v-if="row.reliability"
                                class="reliability"
                                >{{ row.reliability }}</span
                            >
                            <span
                                v-if="row.reliability"
                                class="joint"
                                aria-hidden="true"
                                >{{ " · " }}</span
                            >
                            <span class="row-counts">{{
                                attestedCounts(row)
                            }}</span>
                        </span>
                    </span>
                </li>
            </ul>
            <button
                v-if="hiddenMaterials > 0"
                type="button"
                class="more"
                @click="allMaterials = true"
            >
                <span>{{ moreMaterialsText }}</span>
            </button>
        </section>

        <p
            v-for="missing in absent"
            :key="missing.uri"
            class="absence"
        >
            <span>{{ absenceText(missing.uri) }}</span>
        </p>

        <section class="analyses">
            <h3 class="kicker">{{ $gettext("Analyses here") }}</h3>
            <div class="page-select">
                <SelectAllCheckbox
                    :keys="keys"
                    :name="pageName"
                    :label="$gettext('Add these analyses to the Selection')"
                    :described-by="noticeId"
                    :hints="hints"
                />
                <SelectionCapacityNotice
                    :id="noticeId"
                    :keys="keys"
                    scope="here"
                />
                <BulkStatusLine
                    :status="toggle.lastBulk.value"
                    @undo="toggle.undo"
                    @dismiss="toggle.dismiss"
                    @compare="store.setView('compare')"
                />
            </div>

            <section
                v-for="(view, index) in documents"
                :key="view.document.id"
                class="panel-document"
                :class="{ open: isOpen(view.document.id) }"
            >
                <h4>
                    <button
                        type="button"
                        class="disclosure"
                        :aria-expanded="
                            isOpen(view.document.id) ? 'true' : 'false'
                        "
                        :aria-controls="`${bodyId}-${index}`"
                        @click="toggleDocument(view.document.id)"
                    >
                        <span
                            class="chevron"
                            aria-hidden="true"
                            >{{ isOpen(view.document.id) ? "▾" : "▸" }}</span
                        >
                        <span class="disclosure-text">
                            <span class="title-line">
                                <span
                                    class="group-title"
                                    :lang="view.document.name.lang || undefined"
                                    :title="view.document.name.value"
                                    >{{ view.document.name.value }}</span
                                >
                                <span
                                    v-if="view.dates"
                                    class="dates"
                                    >{{ view.dates }}</span
                                >
                            </span>
                            <span class="summary">
                                <span class="document-counts">{{
                                    documentCounts(view)
                                }}</span>
                                <template v-if="!isOpen(view.document.id)">
                                    <TechniqueTag
                                        v-for="mark in view.techniques"
                                        :key="mark.code"
                                        class="summary-tag"
                                        :code="mark.code"
                                        :colour="mark.colour"
                                    />
                                </template>
                            </span>
                        </span>
                    </button>
                    <SelectAllCheckbox
                        class="group-select"
                        :keys="view.keys"
                        :name="selectName(view.document.name.value)"
                        :described-by="noticeId"
                        :hints="hints"
                        :compact="true"
                    />
                </h4>
                <div
                    v-if="isOpen(view.document.id)"
                    :id="`${bodyId}-${index}`"
                    class="document-body"
                >
                    <a
                        class="open-corpus"
                        :href="
                            documentHref(snapshotOf(store), view.document.id)
                        "
                        @click.prevent="openDocument(view.document.id)"
                    >
                        <span>{{ $gettext("Open in Corpus") }}</span>
                        <svg
                            class="arrow"
                            :viewBox="ICON_VIEW_BOX"
                            aria-hidden="true"
                            focusable="false"
                        >
                            <path
                                v-for="shape in ICONS['arrow-right']"
                                :key="shape"
                                :d="shape"
                            />
                        </svg>
                    </a>
                    <div
                        v-for="entry in shownGroups(view)"
                        :key="entry.key"
                        class="component-group"
                    >
                        <p class="component-line">
                            <span
                                class="component-title"
                                :lang="entry.lang"
                                >{{ entry.title }}</span
                            >
                            <SelectAllCheckbox
                                class="group-select"
                                :keys="entry.keys"
                                :name="selectName(entry.title)"
                                :described-by="noticeId"
                                :hints="hints"
                                :compact="true"
                            />
                        </p>
                        <ul class="events">
                            <li
                                v-for="event in shownEvents(entry)"
                                :key="event.id"
                                class="event"
                            >
                                <p class="event-line">
                                    <span class="type">{{
                                        eventTypeLabel(event.type)
                                    }}</span>
                                    <span class="date">{{
                                        dateOf(event)
                                    }}</span>
                                    <span
                                        v-if="
                                            event.placeSource &&
                                            event.placeSource !== 'own'
                                        "
                                        class="source"
                                        >{{
                                            placeSourceLabel(event.placeSource)
                                        }}</span
                                    >
                                </p>
                                <ul
                                    v-if="event.materials.length > 0"
                                    class="event-materials"
                                >
                                    <li
                                        v-for="material in event.materials"
                                        :key="material.characterization"
                                        class="material"
                                        :class="{
                                            pale: isLow(material, props.low),
                                        }"
                                        :style="materialHue(material)"
                                    >
                                        <span
                                            class="swatch"
                                            :class="{
                                                unknown:
                                                    !props.materials[
                                                        material.id
                                                    ]?.swatch,
                                            }"
                                            aria-hidden="true"
                                        ></span>
                                        <template
                                            v-if="slotOf(material.id) !== null"
                                        >
                                            <span
                                                v-if="
                                                    isLow(material, props.low)
                                                "
                                                class="hollow-dot small"
                                                aria-hidden="true"
                                                >{{ slotOf(material.id) }}</span
                                            >
                                            <FocusSlotDot
                                                v-else
                                                size="small"
                                                :number="
                                                    slotOf(material.id) ?? 0
                                                "
                                            />
                                        </template>
                                        <span
                                            :lang="
                                                material.name.lang || undefined
                                            "
                                            >{{ material.name.value }}</span
                                        >
                                        <span
                                            v-if="reliabilityOf(material)"
                                            class="reliability"
                                            >{{ reliabilityOf(material) }}</span
                                        >
                                    </li>
                                </ul>
                                <p
                                    v-if="placedOnProduction(event)"
                                    class="placed-note"
                                >
                                    <span>{{
                                        $gettext(
                                            "placed on the production (no modification cites it)",
                                        )
                                    }}</span>
                                </p>
                            </li>
                        </ul>
                        <button
                            v-if="hiddenEvents(entry) > 0"
                            type="button"
                            class="more"
                            @click="showAllEvents(entry)"
                        >
                            <span>{{ moreEventsText(entry) }}</span>
                        </button>
                        <ul
                            v-if="entry.analyses.length > 0"
                            class="analysis-list"
                        >
                            <li
                                v-for="id in shownAnalyses(entry)"
                                :key="id"
                            >
                                <SelectionCheckbox
                                    :item-key="analysisKey(id)"
                                    :label="analysisName(id).value"
                                    :hint="hintOf(id)"
                                />
                                <TechniqueTag
                                    v-if="techniqueOf(id)"
                                    class="analysis-technique"
                                    :code="techniqueOf(id)?.code ?? ''"
                                    :colour="techniqueOf(id)?.colour ?? null"
                                />
                                <span
                                    class="analysis-name"
                                    :lang="analysisName(id).lang || undefined"
                                    >{{ analysisName(id).value }}</span
                                >
                            </li>
                        </ul>
                        <p
                            v-if="overCapacity(entry)"
                            class="absence capacity"
                        >
                            <span>{{ capacityText(entry) }}</span>
                            <span>{{ " " }}</span>
                            <a
                                class="open-corpus inline"
                                :href="
                                    documentHref(
                                        snapshotOf(store),
                                        view.document.id,
                                    )
                                "
                                @click.prevent="openDocument(view.document.id)"
                                >{{ $gettext("Open in Corpus") }}</a
                            >
                        </p>
                        <button
                            v-if="hiddenAnalyses(entry) > 0"
                            type="button"
                            class="more"
                            @click="showMoreAnalyses(entry)"
                        >
                            <span>{{ moreAnalysesText(entry) }}</span>
                        </button>
                    </div>
                    <button
                        v-if="hiddenGroups(view) > 0"
                        type="button"
                        class="more more-components"
                        @click="showMoreGroups(view)"
                    >
                        <span>{{ moreGroupsText(view) }}</span>
                    </button>
                </div>
            </section>
            <button
                v-if="hiddenDocuments > 0"
                type="button"
                class="more"
                @click="showMoreDocuments"
            >
                <span>{{ moreDocumentsText }}</span>
            </button>
        </section>

        <footer class="foot">
            <button
                v-if="canCompare"
                type="button"
                class="compare"
                @click="compare"
            >
                <span>{{ compareText }}</span>
            </button>
            <HelpTip
                v-else
                :text="$gettext('Add analyses to the Selection first.')"
            >
                <template #default="{ describedby }">
                    <button
                        type="button"
                        class="compare"
                        aria-disabled="true"
                        :aria-describedby="describedby"
                    >
                        <span>{{ compareText }}</span>
                    </button>
                </template>
            </HelpTip>
            <button
                type="button"
                class="close"
                @click="emit('close')"
            >
                <span>{{ $gettext("Close") }}</span>
            </button>
        </footer>
    </article>
</template>

<style scoped>
.map-panel {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1.25rem;
    min-inline-size: 0;
}

/* AnalysisCard / ComponentCard card head */
.map-panel .card-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.5rem 1rem;
    align-items: center;
}

.map-panel .card-head .name {
    grid-column: 1;
    margin: 0;
    font-family: var(--font-display);
    font-size: 1.25rem;
    font-weight: 500;
    line-height: 1.2;
}

.map-panel .card-head .close-icon {
    grid-column: 2;
    grid-row: 1;
}

.map-panel .meta {
    display: flex;
    flex-wrap: wrap;
    grid-column: 1 / -1;
    gap: 0.5rem;
    align-items: center;
    color: var(--ink-muted);
}

.map-panel .badge {
    padding: 0 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.75rem;
}

/* CorpusDocument .document-bar .chip */
.map-panel .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
}

.map-panel .chip {
    padding: 0.0625rem 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
}

.map-panel .chip.authority {
    color: var(--blue-text);
    text-decoration: none;
}

.map-panel .chip.authority:hover {
    text-decoration: underline;
}

.map-panel .counts-line {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
}

.map-panel section {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.5rem;
}

/* OnThisPage h3 kicker */
.map-panel .kicker {
    margin: 0;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 400;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.map-panel .attested ul,
.map-panel .events,
.map-panel .event-materials,
.map-panel .analysis-list {
    display: grid;
    margin: 0;
    padding: 0;
    list-style: none;
}

.map-panel .attested li {
    display: grid;
    grid-template-columns: 0.875rem 1.125rem minmax(0, 1fr);
    grid-template-areas:
        "sw dot label"
        ". . meta";
    column-gap: 0.5rem;
    align-items: center;
    min-inline-size: 0;
    padding-block: 0.25rem;
}

.map-panel .attested .swatch {
    grid-area: sw;
}

.map-panel .attested .hollow-dot,
.map-panel .attested .spacer,
.map-panel .attested :deep(.focus-slot-dot) {
    grid-area: dot;
}

.map-panel .attested .label {
    grid-area: label;
    min-inline-size: 0;
    overflow-wrap: anywhere;
    white-space: normal;
}

.map-panel .attested .meta {
    display: flex;
    flex-wrap: wrap;
    grid-area: meta;
    gap: 0 0.375rem;
    align-items: baseline;
}

.map-panel .attested .facts {
    white-space: nowrap;
}

.map-panel .reliability {
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.map-panel .joint {
    color: var(--ink-dim);
}

.map-panel .row-counts {
    flex: none;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
}

.map-panel .spacer {
    flex: none;
    inline-size: 1.125rem;
}

/* MaterialsTable .swatch */
.map-panel .swatch {
    flex: none;
    inline-size: 0.875rem;
    block-size: 0.875rem;
    border-radius: 0.25rem;
    background: var(--swatch);
    box-shadow:
        inset 0 0 0 0.0625rem rgb(26 26 46 / 0.18),
        inset 0 0.0625rem 0 rgb(255 255 255 / 0.25);
}

.map-panel .swatch.unknown {
    background: repeating-linear-gradient(
        135deg,
        transparent 0 0.125rem,
        rgb(26 26 46 / 0.22) 0.125rem 0.1875rem
    );
}

.map-panel .pale .swatch:not(.unknown) {
    background: var(--surface);
    box-shadow: inset 0 0 0 0.125rem var(--swatch);
}

/* .ms-focus-pip b.ev: the hollow evidence pip */
.map-panel .hollow-dot {
    display: inline-grid;
    flex: none;
    place-items: center;
    inline-size: 1.125rem;
    block-size: 1.125rem;
    border-radius: 50%;
    background: var(--surface);
    box-shadow: inset 0 0 0 0.09375rem var(--h);
    color: var(--h);
    font: 700 0.625rem/1 var(--font-mono);
    font-variant-numeric: tabular-nums;
}

.map-panel .hollow-dot.small {
    inline-size: 0.875rem;
    block-size: 0.875rem;
    font-size: 0.5rem;
}

.map-panel .absence {
    padding: 0.5rem 0.625rem;
    border-radius: 0.5rem;
    background: var(--bg-warm);
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.map-panel .page-select {
    display: grid;
    gap: 0.5rem;
}

.map-panel .panel-document {
    gap: 0.25rem;
    padding-block-start: 0.5rem;
    border-block-start: 0.0625rem solid var(--border);
}

/* OnThisPage group row, with the MapView rail .disclosure */
.map-panel .panel-document h4 {
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: 0.5rem;
    min-inline-size: 0;
    margin: 0;
    font-size: 0.8125rem;
    font-weight: 600;
}

.map-panel .disclosure {
    display: flex;
    flex: 1 1 auto;
    align-items: baseline;
    gap: 0.375rem;
    min-inline-size: 0;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0.25rem 0;
    border: none;
    background: transparent;
    color: var(--ink);
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.map-panel .disclosure .chevron {
    flex: none;
    color: var(--ink-muted);
}

.map-panel .disclosure-text {
    display: grid;
    gap: 0.125rem;
    min-inline-size: 0;
}

.map-panel .title-line {
    display: flex;
    gap: 0.5rem;
    align-items: baseline;
    min-inline-size: 0;
}

.map-panel .group-title {
    flex: 0 1 auto;
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.map-panel .panel-document h4 .dates {
    flex: none;
    color: var(--ink-muted);
    font-weight: 400;
}

.map-panel .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 0.125rem 0.5rem;
    align-items: center;
    font-weight: 400;
}

.map-panel .document-counts {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-variant-numeric: tabular-nums;
}

.map-panel .summary-tag {
    font-size: 0.6875rem;
}

.map-panel .document-body {
    display: grid;
    gap: 0.25rem;
}

.map-panel .group-select {
    flex: none;
    margin-inline-start: auto;
    font-weight: 400;
}

.map-panel .open-corpus {
    display: inline-flex;
    align-items: center;
    justify-self: start;
    gap: 0.375rem;
    min-block-size: var(--explorer-target, 2.75rem);
    color: var(--blue-text);
    font-size: 0.75rem;
    font-weight: 600;
    text-decoration: none;
}

.map-panel .open-corpus:hover {
    text-decoration: underline;
}

.map-panel .open-corpus.inline {
    display: inline;
    min-block-size: 0;
}

.map-panel .capacity {
    margin-block: 0.25rem;
}

.map-panel .open-corpus .arrow {
    inline-size: 0.875rem;
    block-size: 0.875rem;
    fill: var(--blue-text);
}

/* MaterialsTable nested rule */
.map-panel .component-group {
    display: grid;
    gap: 0.25rem;
    padding-inline-start: 0.75rem;
    border-inline-start: 0.0625rem solid var(--mt-rule, var(--border));
}

.map-panel .component-line {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-inline-size: 0;
}

.map-panel .component-title {
    flex: 0 1 auto;
    min-inline-size: 0;
    overflow: hidden;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    letter-spacing: 0.08em;
    text-overflow: ellipsis;
    text-transform: uppercase;
    white-space: nowrap;
}

.map-panel .event {
    display: grid;
    gap: 0.125rem;
    padding-block: 0.25rem;
}

.map-panel .event-line {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.25rem 0.5rem;
}

.map-panel .event-line .type {
    font-weight: 600;
}

.map-panel .event-line .date {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
}

.map-panel .event-line .source {
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.map-panel .event-materials {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem 0.75rem;
}

.map-panel .material {
    display: inline-flex;
    align-items: center;
    gap: 0.3125rem;
    font-size: 0.75rem;
}

.map-panel .placed-note {
    color: var(--ink-dim);
    font-size: 0.75rem;
    font-style: italic;
}

.map-panel .analysis-list li {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
}

.map-panel .analysis-technique {
    flex: none;
    font-size: 0.6875rem;
}

.map-panel .analysis-name {
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* FacetRail .more */
.map-panel .more {
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.map-panel .more:hover {
    text-decoration: underline;
}

/* CorpusDocument .rail-foot, sticky as RailPanel .show */
.map-panel .foot {
    position: sticky;
    inset-block-end: 0;
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    padding-block: 0.75rem;
    border-block-start: 0.0625rem solid var(--border);
    background: var(--surface);
}

/* CorpusDocument .rail-foot .clear: secondary pill */
.map-panel .pill {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.map-panel .pill:hover {
    border-color: var(--ink-muted);
}

/* UnavailableState ink pill */
.map-panel .compare {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 1.25rem;
    border: 0.0625rem solid var(--ink);
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font: inherit;
    cursor: pointer;
}

.map-panel .compare[aria-disabled="true"] {
    border-color: var(--border-hover);
    background: var(--bg-alt);
    color: var(--ink-dim);
    cursor: not-allowed;
}

.map-panel .close {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.map-panel button:focus-visible,
.map-panel a:focus-visible,
.map-panel .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

@media (forced-colors: active) {
    .map-panel .swatch,
    .map-panel .hollow-dot {
        forced-color-adjust: none;
    }
}
</style>
