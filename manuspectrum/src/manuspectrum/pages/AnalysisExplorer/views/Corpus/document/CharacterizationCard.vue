<script setup lang="ts">
import { computed, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";

import SafeHtml from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SafeHtml.vue";
import SelectionActions from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SelectionActions.vue";
import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

import {
    formatDateRange,
    safeHref,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import {
    analysisKey,
    characterizationKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    CertaintyScale,
    CharacterizationSummary,
    DocumentComponent,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { TechniqueStyle } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

type Material = CharacterizationSummary["materials"][number];
type Source = CharacterizationSummary["sources"][number];

/**
 * `headingId` names the heading (a drawer is labelled by it); `closable:
 * false` hides « Close » where the container has its own. `analysisStyles`
 * holds the technique style of the document's analyses by id: an evidence
 * analysis found there carries its technique code in its family colour, as
 * on the folio. `components` are the document's Components it is linked to
 * (`characterizationComponents`), each a link to its card.
 */
const props = withDefaults(
    defineProps<{
        summary: CharacterizationSummary;
        scale: CertaintyScale;
        headingId?: string;
        closable?: boolean;
        analysisStyles?: ReadonlyMap<string, TechniqueStyle>;
        components?: DocumentComponent[];
    }>(),
    {
        components: () => [],
        headingId: undefined,
        closable: true,
        analysisStyles: () => new Map<string, TechniqueStyle>(),
    },
);

const emit = defineEmits<{ close: [] }>();
defineExpose({ focusHeading });

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const sectionId = useId();
const heading = useTemplateRef<HTMLElement>("heading");

const ownKey = computed(() => characterizationKey(props.summary.id));
/** The material and every analysis it cites, whether or not an analysis holds data to show. */
const withEvidenceKeys = computed(() => [
    ownKey.value,
    ...props.summary.evidence.map((entry) => analysisKey(entry.id)),
]);
const sortedLevels = computed(() =>
    [...props.scale.levels].sort((first, second) => first.rank - second.rank),
);
/** The levels of certainty this identification states, marked on the scale. */
const currentLevels = computed(
    () =>
        new Set(
            props.summary.materials
                .map((entry) => entry.confidence?.uri)
                .filter((uri): uri is string => Boolean(uri)),
        ),
);
const ownHints = computed(
    () =>
        new Map<string, SelectionHint>([
            [
                ownKey.value,
                {
                    title: props.summary.name,
                    kind: $gettext("identified material"),
                },
            ],
        ]),
);
/** The material and each supporting analysis, by its name. */
const withEvidenceHints = computed(() => {
    const hints = new Map(ownHints.value);
    for (const entry of props.summary.evidence) {
        hints.set(analysisKey(entry.id), {
            title: entry.name,
            kind: $gettext("supporting analysis"),
        });
    }
    return hints;
});
const withEvidenceLabel = computed(() =>
    interpolate(
        $ngettext(
            "With its %{n} analysis",
            "With its %{n} analyses",
            props.summary.evidence.length,
        ),
        { n: props.summary.evidence.length },
        true,
    ),
);
const authors = computed(() =>
    props.summary.authors.map((author) => {
        if (author.model === "group") {
            return interpolate($gettext("%{name} (group)"), {
                name: author.name.value,
            });
        }
        if (author.model === "project") {
            return interpolate($gettext("%{name} (project)"), {
                name: author.name.value,
            });
        }
        return author.name.value;
    }),
);

const date = computed(() => formatDateRange(props.summary.date));
/** Each evidence analysis with its technique style, null outside `analysisStyles`. */
const evidence = computed(() =>
    props.summary.evidence.map((entry) => ({
        ...entry,
        style: props.analysisStyles.get(entry.id) ?? null,
    })),
);
const evidenceTitle = computed(() =>
    interpolate(
        $gettext("Analyses cited as evidence (%{n})"),
        { n: props.summary.evidence.length },
        true,
    ),
);

function elementsTitle(level: ValueRef | null): string {
    return level
        ? interpolate(
              $gettext("Elements (%{level})"),
              { level: level.label.value },
              true,
          )
        : $gettext("Elements");
}

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

function openComponent(id: string): void {
    store.focusOn({ kind: "component", id });
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
            <IconButton
                v-if="props.closable"
                class="close"
                icon="times"
                :label="$gettext('Close the card')"
                :description="$gettext('Escape')"
                @click="close"
            />
            <p class="meta">
                <span>{{ $gettext("Identified material") }}</span>
                <span
                    v-if="props.summary.unpublished"
                    class="badge draft"
                >
                    {{ $gettext("Draft") }}
                </span>
            </p>
        </header>

        <p
            v-if="props.summary.zone?.source === 'component'"
            class="note-line"
        >
            <span>{{ $gettext("Zone of the observed component.") }}</span>
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
            <template v-if="props.components.length > 0">
                <dt>
                    <span>{{ $gettext("Component") }}</span>
                </dt>
                <dd>
                    <ul class="component-links">
                        <li
                            v-for="component in props.components"
                            :key="component.id"
                        >
                            <button
                                type="button"
                                class="component-link"
                                :lang="component.name.lang"
                                @click="openComponent(component.id)"
                            >
                                <span>{{ component.name.value }}</span>
                            </button>
                        </li>
                    </ul>
                </dd>
            </template>
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
                    <span>{{ elementsTitle(group.level) }}</span>
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
                    <span>{{ authors.join(", ") }}</span>
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
                    :class="{ 'is-current': currentLevels.has(level.uri) }"
                    :lang="level.label.lang"
                    :aria-current="
                        currentLevels.has(level.uri) ? 'true' : undefined
                    "
                >
                    <span>{{ level.label.value }}</span>
                    <span
                        v-if="currentLevels.has(level.uri)"
                        class="visually-hidden"
                        >{{ $gettext("this identification") }}</span
                    >
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
                    v-for="entry in evidence"
                    :key="entry.id"
                >
                    <button
                        type="button"
                        @click="openAnalysis(entry.id)"
                    >
                        <TechniqueCode
                            v-if="entry.style"
                            :code="entry.style.code"
                            :colour="entry.style.colour"
                        />
                        <span
                            class="name"
                            :lang="entry.name.lang"
                            >{{ entry.name.value }}</span
                        >
                    </button>
                </li>
            </ul>
        </section>

        <SelectionActions
            v-if="props.summary.evidence.length > 0"
            :title="$gettext('Add to the Selection')"
            :primary="{
                keys: withEvidenceKeys,
                label: withEvidenceLabel,
                hints: withEvidenceHints,
            }"
            :secondary="{
                keys: [ownKey],
                label: $gettext('The material alone'),
                hints: ownHints,
            }"
        />
        <SelectionActions
            v-else
            :title="$gettext('Add to the Selection')"
            :primary="{
                keys: [ownKey],
                label: $gettext('Add the material'),
                hints: ownHints,
            }"
        />
    </article>
</template>

<style scoped>
.characterization-card {
    display: grid;
    gap: 1rem;
    container-type: inline-size;
}

.characterization-card .card-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0.5rem 1rem;
    align-items: center;
}

.characterization-card .card-head > * {
    grid-column: 1 / -1;
}

.characterization-card .card-head .name {
    grid-column: 1;
    font-weight: 600;
}

.characterization-card .card-head .icon-button {
    grid-column: 2;
    grid-row: 1;
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

.characterization-card .evidence button {
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.characterization-card .component-link {
    padding: 0;
    border: none;
    background: none;
    color: var(--blue-text);
    font: inherit;
    text-align: start;
    text-decoration: underline;
    cursor: pointer;
}

.characterization-card a:focus-visible,
.characterization-card button:focus-visible,
.characterization-card .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
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

.characterization-card .scale ol {
    grid-auto-columns: minmax(0, 1fr);
    grid-auto-flow: column;
    gap: 0.125rem;
    padding: 0;
    list-style: none;
}

.characterization-card .scale li {
    padding-block-start: 0.375rem;
    border-block-start: 0.375rem solid var(--border-hover);
    color: var(--ink-muted);
    font-size: 0.8125rem;
    overflow-wrap: anywhere;
}

.characterization-card .scale .is-current {
    border-block-start-color: var(--ink);
    color: var(--ink);
    font-weight: 600;
}

@container (max-width: 20rem) {
    .characterization-card .scale ol {
        grid-auto-flow: row;
    }
}

.characterization-card .evidence button {
    gap: 0.5rem;
    text-align: start;
}

.characterization-card .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
