<script setup lang="ts">
import { computed, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import AddToSelection from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AddToSelection.vue";
import SafeHtml from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SafeHtml.vue";

import { useEvidence } from "@/manuspectrum/pages/AnalysisExplorer/composables/useEvidence.ts";
import {
    formatDateRange,
    safeHref,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import {
    characterizationKey,
    evidenceEntries,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    CertaintyScale,
    CharacterizationSummary,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

type Material = CharacterizationSummary["materials"][number];
type Source = CharacterizationSummary["sources"][number];

/** `headingId` names the heading (a drawer is labelled by it); `closable: false` hides « Close » where the container has its own. */
const props = withDefaults(
    defineProps<{
        summary: CharacterizationSummary;
        scale: CertaintyScale;
        headingId?: string;
        closable?: boolean;
    }>(),
    { headingId: undefined, closable: true },
);

const emit = defineEmits<{ close: [] }>();
defineExpose({ focusHeading });

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const evidence = useEvidence(() => props.summary.evidence);
const sectionId = useId();
const heading = useTemplateRef<HTMLElement>("heading");

const ownKey = computed(() => characterizationKey(props.summary.id));
/** The evidence analyses read for this material; null while they load or when the data held is another material's. */
const evidenceRead = computed(() => {
    const read = evidence.data.value;
    if (evidence.status.value !== "ready" || !read) return null;
    const ids = read.map((analysis) => analysis.id);
    return ids.length === props.summary.evidence.length &&
        ids.every((id, index) => id === props.summary.evidence[index])
        ? read
        : null;
});
const names = computed(
    () =>
        new Map(
            (evidenceRead.value ?? []).map((analysis) => [
                analysis.id,
                analysis.name,
            ]),
        ),
);
const entries = computed(() =>
    evidenceRead.value ? evidenceEntries(evidenceRead.value) : null,
);
const withEvidenceKeys = computed(() =>
    entries.value ? [ownKey.value, ...entries.value.keys] : [],
);
const readFailed = computed(
    () =>
        evidence.status.value === "error" ||
        evidence.status.value === "unavailable",
);
const sortedLevels = computed(() =>
    [...props.scale.levels].sort((first, second) => first.rank - second.rank),
);
const date = computed(() => formatDateRange(props.summary.date));
const withoutDataNote = computed(() => {
    const count = entries.value?.withoutData.length ?? 0;
    return count === 0
        ? ""
        : interpolate(
              $ngettext(
                  "%{n} supporting analysis has no data to show and is left out.",
                  "%{n} supporting analyses have no data to show and are left out.",
                  count,
              ),
              { n: count },
              true,
          );
});
const evidenceTitle = computed(() =>
    interpolate(
        $gettext("Analyses cited as evidence (%{n})"),
        { n: props.summary.evidence.length },
        true,
    ),
);

function labels(values: ValueRef[]): string {
    return values.map((value) => value.label.value).join(", ");
}

function proportionText(entry: Material): string {
    if (!entry.proportion) return "";
    const unit = entry.proportion.unit?.label.value;
    return unit
        ? `${entry.proportion.value} ${unit}`
        : String(entry.proportion.value);
}

function sourceText(source: Source): string {
    return source.title?.value ?? source.ref?.name.value ?? source.url ?? "";
}

function evidenceName(id: string, index: number): string {
    return (
        names.value.get(id)?.value ??
        interpolate($gettext("Analysis %{n}"), { n: index + 1 }, true)
    );
}

function openAnalysis(id: string): void {
    store.focusOn({ kind: "analysis", id });
}

function close(): void {
    emit("close");
}

function focusHeading(): void {
    heading.value?.focus();
}
</script>

<template>
    <article class="characterization-card">
        <header class="card-head">
            <h3
                :id="props.headingId"
                ref="heading"
                class="name"
                tabindex="-1"
                :lang="props.summary.name.lang"
            >
                <span>{{ props.summary.name.value }}</span>
            </h3>
            <p class="meta">
                <span>{{ $gettext("Identified material") }}</span>
                <span
                    v-if="props.summary.unpublished"
                    class="badge draft"
                >
                    {{ $gettext("Draft") }}
                </span>
            </p>
            <button
                v-if="props.closable"
                type="button"
                class="close"
                @click="close"
            >
                <span>{{ $gettext("Close") }}</span>
            </button>
        </header>

        <p
            v-if="props.summary.zone?.source === 'component'"
            class="note-line"
        >
            <span>{{ $gettext("Zone of the observed part.") }}</span>
        </p>

        <section
            class="materials"
            :aria-labelledby="`${sectionId}-materials`"
        >
            <h4 :id="`${sectionId}-materials`">
                <span>{{ $gettext("Identified materials") }}</span>
            </h4>
            <ul>
                <li
                    v-for="entry in props.summary.materials"
                    :key="entry.value.uri"
                >
                    <span :lang="entry.value.label.lang">
                        {{ entry.value.label.value }}
                    </span>
                    <span
                        v-if="entry.confidence"
                        class="badge certainty"
                        :lang="entry.confidence.label.lang"
                    >
                        {{ entry.confidence.label.value }}
                    </span>
                    <span
                        v-if="entry.proportion"
                        class="proportion"
                    >
                        {{ proportionText(entry) }}
                    </span>
                </li>
            </ul>
        </section>

        <dl class="details">
            <template v-if="props.summary.colours.length > 0">
                <dt>
                    <span>{{ $gettext("Colour") }}</span>
                </dt>
                <dd>
                    <span>{{ labels(props.summary.colours) }}</span>
                </dd>
            </template>
            <template v-if="props.summary.layers.length > 0">
                <dt>
                    <span>{{ $gettext("Layer") }}</span>
                </dt>
                <dd>
                    <span>{{ labels(props.summary.layers) }}</span>
                </dd>
            </template>
            <template
                v-for="(group, index) in props.summary.elements"
                :key="index"
            >
                <dt :lang="group.level?.label.lang">
                    <span>
                        {{ group.level?.label.value ?? $gettext("Elements") }}
                    </span>
                </dt>
                <dd>
                    <span>{{ labels(group.values) }}</span>
                </dd>
            </template>
            <template v-if="props.summary.authors.length > 0">
                <dt>
                    <span>{{ $gettext("Authors of the identification") }}</span>
                </dt>
                <dd>
                    <span>
                        {{
                            props.summary.authors
                                .map((author) => author.name.value)
                                .join(", ")
                        }}
                    </span>
                </dd>
            </template>
            <template v-if="date">
                <dt>
                    <span>{{ $gettext("Date of the identification") }}</span>
                </dt>
                <dd>
                    <span>{{ date }}</span>
                </dd>
            </template>
        </dl>

        <section
            v-if="props.summary.note"
            class="note"
            :aria-labelledby="`${sectionId}-note`"
        >
            <h4 :id="`${sectionId}-note`">
                <span>{{ $gettext("Interpretation note") }}</span>
            </h4>
            <SafeHtml
                :html="props.summary.note.html"
                :lang="props.summary.note.lang"
            />
        </section>

        <section
            v-if="props.summary.sources.length > 0"
            class="sources"
            :aria-labelledby="`${sectionId}-sources`"
        >
            <h4 :id="`${sectionId}-sources`">
                <span>{{ $gettext("Sources") }}</span>
            </h4>
            <ul>
                <li
                    v-for="(source, index) in props.summary.sources"
                    :key="index"
                >
                    <a
                        v-if="safeHref(source.url)"
                        rel="noopener"
                        target="_blank"
                        :href="safeHref(source.url)!"
                    >
                        <span>{{ sourceText(source) }}</span>
                    </a>
                    <span v-else>{{ sourceText(source) }}</span>
                </li>
            </ul>
        </section>

        <section
            v-if="sortedLevels.length > 0"
            class="scale"
            :aria-labelledby="`${sectionId}-scale`"
        >
            <h4 :id="`${sectionId}-scale`">
                <span>{{ $gettext("Degree of certainty") }}</span>
            </h4>
            <ol>
                <li
                    v-for="level in sortedLevels"
                    :key="level.uri"
                    :lang="level.label.lang"
                >
                    <span>{{ level.label.value }}</span>
                </li>
            </ol>
        </section>

        <section
            v-if="props.summary.evidence.length > 0"
            class="evidence"
            :aria-labelledby="`${sectionId}-evidence`"
        >
            <h4 :id="`${sectionId}-evidence`">
                <span>{{ evidenceTitle }}</span>
            </h4>
            <ul>
                <li
                    v-for="(id, index) in props.summary.evidence"
                    :key="id"
                >
                    <button
                        type="button"
                        @click="openAnalysis(id)"
                    >
                        <span>{{ evidenceName(id, index) }}</span>
                    </button>
                </li>
            </ul>
        </section>

        <div class="alone">
            <AddToSelection
                :keys="[ownKey]"
                :label="$gettext('+ Selection (the material alone)')"
            />
        </div>
        <div
            v-if="props.summary.evidence.length > 0"
            class="with-evidence"
        >
            <p
                v-if="readFailed"
                class="warning"
            >
                <span>
                    {{
                        $gettext(
                            "The supporting analyses could not be read; add the material alone.",
                        )
                    }}
                </span>
            </p>
            <template v-else-if="entries">
                <AddToSelection
                    :keys="withEvidenceKeys"
                    :label="
                        $gettext('+ Selection with its supporting analyses')
                    "
                />
                <p
                    v-if="withoutDataNote"
                    class="note-line"
                >
                    <span>{{ withoutDataNote }}</span>
                </p>
            </template>
        </div>
    </article>
</template>

<style scoped>
.characterization-card {
    display: grid;
    gap: 1rem;
    container-type: inline-size;
}

.characterization-card .card-head {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    align-items: center;
}

.characterization-card .card-head .name {
    flex: 1 1 100%;
    font-weight: 600;
}

.characterization-card .card-head .close {
    margin-inline-start: auto;
}

.characterization-card .meta,
.characterization-card .materials li {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
}

.characterization-card .meta,
.characterization-card .note-line,
.characterization-card .proportion {
    color: var(--ink-muted);
}

.characterization-card .note-line {
    font-size: 0.875rem;
}

.characterization-card h4,
.characterization-card dt {
    font-weight: 600;
}

.characterization-card section {
    display: grid;
    gap: 0.5rem;
}

.characterization-card .badge {
    padding: 0 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.75rem;
}

.characterization-card .certainty {
    background: var(--bg-alt);
    color: var(--ink);
}

.characterization-card ul {
    display: grid;
    gap: 0.5rem;
    padding: 0;
    list-style: none;
}

.characterization-card ol {
    display: grid;
    gap: 0.25rem;
    padding-inline-start: 1.25rem;
}

.characterization-card a,
.characterization-card button {
    display: inline-flex;
    align-items: center;
    min-block-size: var(--explorer-target, 2.75rem);
}

.characterization-card a {
    color: var(--blue-text);
}

.characterization-card .card-head .close,
.characterization-card .evidence button {
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.characterization-card a:focus-visible,
.characterization-card button:focus-visible,
.characterization-card .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.characterization-card .warning {
    color: var(--ink);
    font-weight: 600;
}

.characterization-card dl {
    display: grid;
    grid-template-columns: minmax(8rem, auto) 1fr;
    gap: 0.25rem 1rem;
}

@container (max-width: 30rem) {
    .characterization-card dl {
        grid-template-columns: 1fr;
    }
}
</style>
