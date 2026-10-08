<script setup lang="ts">
import { computed, ref } from "vue";
import { useGettext } from "vue3-gettext";

import SelectAllCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectAllCheckbox.vue";
import SelectionCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionCheckbox.vue";
import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

import { analysisKey } from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { techniqueKey } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type {
    CharacterizationSummary,
    DocumentComponent,
    SampleSummary,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    Annotation,
    UnlocatedAnalysis,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";
import type { TechniqueStyle } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import type {
    Focus,
    FolioView,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const SEPARATOR = /\s+[—–-]\s+/;

/**
 * What the page shows, listed. A row name drops the page label and the
 * document it ends with (`pageLabel`, `documentName`: the screen says them
 * already). The analyses without a position fold under their count when
 * the page has analyses of its own. A row outside the filters is greyed and
 * ends with an « outside filters » badge, which is part of its accessible
 * name; a technique group whose analyses are all outside the filters comes
 * after the groups holding a kept one.
 * Each analysis has its Selection checkbox; a « select all » covers the
 * page, each technique group and the analyses without a position, counting
 * only the rows listed. `hiddenCount` is how many analyses outside the
 * filters the screen leaves out of the lists. `components` are the
 * Components placed on the page or observed by one of its analyses: the
 * analyses view lists them under the analyses, each one opening its card.
 */
const props = withDefaults(
    defineProps<{
        annotations: Annotation[];
        unlocated: UnlocatedAnalysis[];
        characterizations: CharacterizationSummary[];
        samples: SampleSummary[];
        styles: Map<string, TechniqueStyle>;
        view: FolioView;
        pageLabel?: string;
        documentName?: string;
        hiddenCount?: number;
        components?: DocumentComponent[];
    }>(),
    {
        pageLabel: "",
        documentName: "",
        hiddenCount: 0,
        components: () => [],
    },
);
const emit = defineEmits<{ select: [focus: Focus] }>();

const { $gettext, $ngettext, interpolate } = useGettext();

const unlocatedOpen = ref(props.annotations.length === 0);

/** One entry per analysis (an analysis may have several zones), grouped in the order of the technique styles. */
const groups = computed(() => {
    const seen = new Set<string>();
    const byTechnique = new Map<string, Annotation[]>();
    for (const annotation of props.annotations) {
        if (seen.has(annotation.analysis)) continue;
        seen.add(annotation.analysis);
        const key = techniqueKey(annotation.technique);
        byTechnique.set(key, [...(byTechnique.get(key) ?? []), annotation]);
    }
    const listed = [...props.styles.values()]
        .filter((style) => byTechnique.has(style.key))
        .map((style) => ({ style, items: byTechnique.get(style.key)! }));
    const kept = (group: { items: Annotation[] }) =>
        group.items.some((item) => item.match);
    return [...listed.filter(kept), ...listed.filter((g) => !kept(g))];
});

/** The message of a view with nothing to list; null when the view lists something. */
const emptyMessage = computed(() => {
    if (props.view === "characterizations") {
        return props.characterizations.length === 0
            ? $gettext("No identified material on this page.")
            : null;
    }
    if (props.view === "samples") {
        return props.samples.length === 0
            ? $gettext("No sample on this page.")
            : null;
    }
    return props.annotations.length === 0 && props.unlocated.length === 0
        ? $gettext("No published analysis on this page.")
        : null;
});

const groupKeys = (items: { analysis: string }[]): string[] =>
    items.map((item) => analysisKey(item.analysis));

/** The Selection keys of the page: the analyses of the groups and, when the list is open, those without a position. */
const pageKeys = computed(() => [
    ...groups.value.flatMap((group) => groupKeys(group.items)),
    ...(unlocatedOpen.value ? groupKeys(props.unlocated) : []),
]);
const unlocatedKeys = computed(() => groupKeys(props.unlocated));
const hints = computed(
    () =>
        new Map<string, SelectionHint>(
            [
                ...groups.value.flatMap((group) => group.items),
                ...props.unlocated,
            ].map((item) => [
                analysisKey(item.analysis),
                { title: item.name, kind: $gettext("analysis") },
            ]),
        ),
);
const outsideText = computed(() => $gettext("outside filters"));
const pageSelectLabel = computed(() => selectAllLabel(pageKeys.value.length));
const hiddenNote = computed(() =>
    interpolate(
        $ngettext(
            "%{n} analysis outside the filters is hidden.",
            "%{n} analyses outside the filters are hidden.",
            props.hiddenCount,
        ),
        { n: props.hiddenCount },
        true,
    ),
);

function selectAllLabel(count: number): string {
    return interpolate($gettext("Select all (%{n} shown)"), { n: count }, true);
}

function groupSelectLabel(name: string, count: number): string {
    return interpolate(
        $gettext("Select all: %{name} (%{n} shown)"),
        { name, n: count },
        true,
    );
}

function addLabel(name: string): string {
    return interpolate(
        $gettext("Add %{name} to the Selection"),
        { name },
        true,
    );
}

function removeLabel(name: string): string {
    return interpolate(
        $gettext("Remove %{name} from the Selection"),
        { name },
        true,
    );
}

const unlocatedTitle = computed(() =>
    interpolate(
        $gettext("Without a position on the image (%{n})"),
        { n: props.unlocated.length },
        true,
    ),
);

/**
 * `name` without its trailing context: from the segment that is this page's
 * label when at most one segment (the document) follows it, else without a
 * last segment that is the document's name. Segments are separated by a
 * spaced dash.
 */
function shortName(name: string): string {
    const parts = name.split(SEPARATOR);
    const page = props.pageLabel.trim();
    const at = page ? parts.lastIndexOf(page) : -1;
    if (at >= 1 && at >= parts.length - 2) {
        return parts.slice(0, at).join(" — ");
    }
    const document = props.documentName.trim();
    if (parts.length > 1 && document && parts.at(-1) === document) {
        return parts.slice(0, -1).join(" — ");
    }
    return name;
}

function toggleUnlocated(): void {
    unlocatedOpen.value = !unlocatedOpen.value;
}

function select(focus: Focus): void {
    emit("select", focus);
}
</script>

<template>
    <section
        class="on-this-page"
        aria-labelledby="on-this-page-title"
    >
        <h3
            id="on-this-page-title"
            tabindex="-1"
        >
            <span>{{ $gettext("On this page") }}</span>
        </h3>
        <p
            v-if="emptyMessage"
            class="empty"
        >
            <span>{{ emptyMessage }}</span>
        </p>
        <p
            v-if="props.view === 'analyses' && props.hiddenCount > 0"
            class="hidden-note"
        >
            <span>{{ hiddenNote }}</span>
        </p>
        <div
            v-if="props.view === 'analyses' && pageKeys.length > 0"
            class="page-select"
        >
            <SelectAllCheckbox
                :keys="pageKeys"
                :label="pageSelectLabel"
                :hints="hints"
            />
        </div>
        <template v-if="props.view === 'analyses'">
            <section
                v-for="group in groups"
                :key="group.style.key"
                class="technique"
            >
                <h4>
                    <TechniqueCode
                        :code="group.style.code"
                        :colour="group.style.colour"
                    />
                    <span
                        class="group-title"
                        :lang="group.style.label.lang || undefined"
                        :title="group.style.label.value"
                    >
                        {{ group.style.label.value }}
                    </span>
                    <SelectAllCheckbox
                        class="group-select"
                        :compact="true"
                        :keys="groupKeys(group.items)"
                        :label="
                            groupSelectLabel(
                                group.style.label.value,
                                group.items.length,
                            )
                        "
                        :hints="hints"
                    />
                </h4>
                <ul>
                    <li
                        v-for="item in group.items"
                        :key="item.analysis"
                        :class="{ 'is-dimmed': !item.match }"
                    >
                        <SelectionCheckbox
                            :item-key="analysisKey(item.analysis)"
                            :label="addLabel(item.name.value)"
                            :held-label="removeLabel(item.name.value)"
                            :hint="hints.get(analysisKey(item.analysis))"
                        />
                        <button
                            type="button"
                            :data-focus="`analysis:${item.analysis}`"
                            :title="item.name.value"
                            @click="
                                select({ kind: 'analysis', id: item.analysis })
                            "
                        >
                            <span :lang="item.name.lang">{{
                                shortName(item.name.value)
                            }}</span>
                            <span
                                v-if="!item.match"
                                class="outside"
                            >
                                {{ outsideText }}
                            </span>
                        </button>
                        <span
                            v-if="item.unpublished"
                            class="draft"
                        >
                            {{ $gettext("Draft") }}
                        </span>
                    </li>
                </ul>
            </section>
        </template>
        <section
            v-if="
                props.view === 'characterizations' &&
                props.characterizations.length > 0
            "
            class="materials"
        >
            <h4>
                <span>{{ $gettext("Identified materials") }}</span>
            </h4>
            <ul>
                <li
                    v-for="summary in props.characterizations"
                    :key="summary.id"
                >
                    <button
                        type="button"
                        :data-focus="`characterization:${summary.id}`"
                        @click="
                            select({ kind: 'characterization', id: summary.id })
                        "
                    >
                        <span :lang="summary.name.lang">{{
                            summary.name.value
                        }}</span>
                    </button>
                    <span
                        v-if="summary.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>
        <section
            v-if="props.view === 'samples' && props.samples.length > 0"
            class="samples"
        >
            <h4>
                <span>{{ $gettext("Samples") }}</span>
            </h4>
            <ul>
                <li
                    v-for="entry in props.samples"
                    :key="entry.id"
                >
                    <button
                        type="button"
                        :data-focus="`sample:${entry.id}`"
                        @click="select({ kind: 'sample', id: entry.id })"
                    >
                        <span :lang="entry.name.lang">{{
                            entry.name.value
                        }}</span>
                    </button>
                    <span
                        v-if="entry.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>
        <section
            v-if="props.view === 'analyses' && props.components.length > 0"
            class="components"
        >
            <h4>
                <span>{{ $gettext("Components on this page") }}</span>
            </h4>
            <ul>
                <li
                    v-for="entry in props.components"
                    :key="entry.id"
                >
                    <button
                        type="button"
                        :data-focus="`component:${entry.id}`"
                        @click="select({ kind: 'component', id: entry.id })"
                    >
                        <span :lang="entry.name.lang">{{
                            entry.name.value
                        }}</span>
                    </button>
                    <span
                        v-if="entry.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>
        <section
            v-if="props.view === 'analyses' && props.unlocated.length > 0"
            class="unlocated"
        >
            <h4>
                <button
                    type="button"
                    class="fold"
                    :aria-expanded="unlocatedOpen ? 'true' : 'false'"
                    @click="toggleUnlocated"
                >
                    <span>{{ unlocatedTitle }}</span>
                </button>
                <SelectAllCheckbox
                    v-if="unlocatedOpen"
                    class="group-select"
                    :compact="true"
                    :keys="unlocatedKeys"
                    :label="selectAllLabel(unlocatedKeys.length)"
                    :hints="hints"
                />
            </h4>
            <ul v-if="unlocatedOpen">
                <li
                    v-for="item in props.unlocated"
                    :key="item.analysis"
                    :class="{ 'is-dimmed': !item.match }"
                >
                    <SelectionCheckbox
                        :item-key="analysisKey(item.analysis)"
                        :label="addLabel(item.name.value)"
                        :held-label="removeLabel(item.name.value)"
                        :hint="hints.get(analysisKey(item.analysis))"
                    />
                    <button
                        type="button"
                        :data-focus="`unlocated:${item.analysis}`"
                        :title="item.name.value"
                        @click="select({ kind: 'analysis', id: item.analysis })"
                    >
                        <span :lang="item.name.lang">{{
                            shortName(item.name.value)
                        }}</span>
                        <span
                            v-if="!item.match"
                            class="outside"
                        >
                            {{ outsideText }}
                        </span>
                    </button>
                    <span
                        v-if="item.unpublished"
                        class="draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>
    </section>
</template>

<style scoped>
.on-this-page {
    display: grid;
    gap: 1rem;
}

.on-this-page h3 {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 400;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.on-this-page h3:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.on-this-page .empty {
    color: var(--ink-muted);
}

.on-this-page section {
    display: grid;
    gap: 0.5rem;
}

.on-this-page h4 {
    display: flex;
    flex-wrap: nowrap;
    align-items: center;
    gap: 0.5rem;
    min-inline-size: 0;
    font-size: 0.8125rem;
    font-weight: 600;
}

.on-this-page ul {
    display: grid;
    gap: 0;
    padding: 0;
    list-style: none;
}

.on-this-page li {
    display: flex;
    flex-wrap: nowrap;
    align-items: flex-start;
    gap: 0.5rem;
}

.on-this-page li > button {
    overflow-wrap: anywhere;
}

.on-this-page li.is-dimmed {
    color: var(--ink-muted);
}

.on-this-page li.is-dimmed > button {
    color: var(--ink-muted);
}

.on-this-page .outside {
    flex: none;
    margin-inline-start: 0.5rem;
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    color: var(--ink-muted);
    font-size: 0.6875rem;
    white-space: nowrap;
}

.on-this-page .hidden-note {
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.on-this-page .group-title {
    flex: 1 1 0;
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.on-this-page .group-select {
    flex: none;
    flex-wrap: nowrap;
    margin-inline-start: auto;
    font-weight: 400;
}

.on-this-page button {
    display: inline-flex;
    flex: 1 1 0;
    align-items: center;
    justify-content: flex-start;
    min-inline-size: 0;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.on-this-page button:hover {
    background: var(--bg-alt);
}

.on-this-page button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.on-this-page .fold {
    font-weight: 600;
}

.on-this-page .fold > span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.on-this-page .fold::before {
    content: "▸" / "";
    margin-inline-end: 0.375rem;
}

.on-this-page .fold[aria-expanded="true"]::before {
    content: "▾" / "";
}

.on-this-page .draft {
    color: var(--ink-muted);
    font-size: 0.75rem;
}
</style>
