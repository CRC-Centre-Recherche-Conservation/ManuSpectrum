<script setup lang="ts">
import { computed, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import SelectAllCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectAllCheckbox.vue";
import SelectionCheckbox from "@/manuspectrum/pages/AnalysisExplorer/components/SelectionCheckbox.vue";
import SelectionActions from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SelectionActions.vue";
import TechniqueCode from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/TechniqueCode.vue";

import {
    analysisKey,
    characterizationKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { DocumentComponent } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    ComponentAnalysis,
    ComponentMaterial,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/component-analyses.ts";
import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * A Component of the document, the analyses made on it here and the
 * identified materials linked to it (`componentMaterials`). Each has its
 * Selection checkbox and opens its own card; the analyses have a « select
 * all ». The primary button adds the analyses and the materials, the
 * secondary one the analyses alone, each all or none (`an:` and `ch:` keys: a
 * Component is never in the Selection itself). `headingId` names the heading (a drawer is labelled by
 * it); `closable: false` hides « Close the card » where the container has its
 * own.
 */
const props = withDefaults(
    defineProps<{
        component: DocumentComponent;
        analyses: ComponentAnalysis[];
        materials?: ComponentMaterial[];
        headingId?: string;
        closable?: boolean;
    }>(),
    { materials: () => [], headingId: undefined, closable: true },
);

const emit = defineEmits<{ close: [] }>();
defineExpose({ focusHeading });

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const sectionId = useId();
const heading = useTemplateRef<HTMLElement>("heading");

const keys = computed(() =>
    props.analyses.map((entry) => analysisKey(entry.id)),
);
const hints = computed(
    () =>
        new Map<string, SelectionHint>(
            props.analyses.map((entry) => [
                analysisKey(entry.id),
                {
                    title: entry.name,
                    kind: interpolate(
                        $gettext("analysis of component %{name}"),
                        { name: props.component.name.value },
                        true,
                    ),
                },
            ]),
        ),
);
const materialKeys = computed(() =>
    props.materials.map((entry) => characterizationKey(entry.id)),
);
const allKeys = computed(() => [...keys.value, ...materialKeys.value]);
const allHints = computed(() => {
    const merged = new Map(hints.value);
    for (const entry of props.materials) {
        merged.set(characterizationKey(entry.id), {
            title: entry.name,
            kind: interpolate(
                $gettext("identified material of component %{name}"),
                { name: props.component.name.value },
                true,
            ),
        });
    }
    return merged;
});
const materialsTitle = computed(() =>
    interpolate(
        $gettext("Identified materials (%{n})"),
        { n: props.materials.length },
        true,
    ),
);
const analysesTitle = computed(() =>
    interpolate(
        $gettext("Analyses on this component (%{n})"),
        { n: props.analyses.length },
        true,
    ),
);
const zonesText = computed(() => {
    const zones = props.component.zones;
    if (zones.length === 0) return $gettext("No zone");
    const pages = new Set(zones.map((zone) => zone.canvas)).size;
    return interpolate(
        $gettext("%{zones} on %{pages}"),
        {
            zones: interpolate(
                $ngettext("%{n} zone", "%{n} zones", zones.length),
                { n: zones.length },
                true,
            ),
            pages: interpolate(
                $ngettext("%{n} page", "%{n} pages", pages),
                { n: pages },
                true,
            ),
        },
        true,
    );
});
const analysesCount = computed(() =>
    interpolate(
        $ngettext("%{n} analysis", "%{n} analyses", props.analyses.length),
        { n: props.analyses.length },
        true,
    ),
);
const materialsCount = computed(() =>
    interpolate(
        $ngettext("%{n} material", "%{n} materials", props.materials.length),
        { n: props.materials.length },
        true,
    ),
);
const addAllLabel = computed(() => {
    const { analyses, materials } = props;
    if (materials.length === 0) {
        return interpolate(
            $ngettext(
                "With its %{n} analysis",
                "With its %{n} analyses",
                analyses.length,
            ),
            { n: analyses.length },
            true,
        );
    }
    if (analyses.length === 0) {
        return interpolate(
            $ngettext(
                "With its %{n} material",
                "With its %{n} materials",
                materials.length,
            ),
            { n: materials.length },
            true,
        );
    }
    return interpolate(
        $gettext("With its %{analyses} and %{materials}"),
        { analyses: analysesCount.value, materials: materialsCount.value },
        true,
    );
});
const selectAllLabel = computed(() =>
    interpolate(
        $gettext("Select all (%{n} shown)"),
        { n: props.analyses.length },
        true,
    ),
);
const outsideText = computed(() => $gettext("(outside the filters)"));

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

function openAnalysis(id: string): void {
    store.focusOn({ kind: "analysis", id });
}

function openMaterial(id: string): void {
    store.focusOn({ kind: "characterization", id });
}

function close(): void {
    emit("close");
}

function focusHeading(): void {
    heading.value?.focus();
}
</script>

<template>
    <article class="component-card">
        <header class="card-head">
            <h3
                :id="props.headingId"
                ref="heading"
                class="name"
                tabindex="-1"
                :lang="props.component.name.lang"
            >
                <span>{{ props.component.name.value }}</span>
            </h3>
            <p class="meta">
                <span>{{ $gettext("Component") }}</span>
                <span>{{ zonesText }}</span>
                <span
                    v-if="props.component.unpublished"
                    class="badge draft"
                >
                    {{ $gettext("Draft") }}
                </span>
            </p>
            <IconButton
                v-if="props.closable"
                class="close"
                icon="times"
                :label="$gettext('Close the card')"
                :description="$gettext('Escape')"
                @click="close"
            />
        </header>

        <SelectionActions
            v-if="props.analyses.length > 0 || props.materials.length > 0"
            :title="$gettext('Add to the Selection')"
            :primary="{
                keys: allKeys,
                label: addAllLabel,
                hints: allHints,
            }"
            :secondary="
                props.analyses.length > 0 && props.materials.length > 0
                    ? {
                          keys,
                          label: $gettext('The analyses alone'),
                          hints,
                      }
                    : null
            "
        />

        <section
            class="analyses"
            :aria-labelledby="`${sectionId}-analyses`"
        >
            <h4 :id="`${sectionId}-analyses`">
                <span>{{ analysesTitle }}</span>
            </h4>
            <p
                v-if="props.analyses.length === 0"
                class="empty"
            >
                <span>{{
                    $gettext("No analysis of this document observes it.")
                }}</span>
            </p>
            <SelectAllCheckbox
                v-else
                :keys="keys"
                :label="selectAllLabel"
                :hints="hints"
            />
            <ul v-if="props.analyses.length > 0">
                <li
                    v-for="entry in props.analyses"
                    :key="entry.id"
                    :class="{ 'is-dimmed': !entry.match }"
                >
                    <SelectionCheckbox
                        :item-key="analysisKey(entry.id)"
                        :label="addLabel(entry.name.value)"
                        :held-label="removeLabel(entry.name.value)"
                        :hint="hints.get(analysisKey(entry.id))"
                    />
                    <TechniqueCode
                        v-if="entry.style"
                        :code="entry.style.code"
                        :colour="entry.style.colour"
                    />
                    <button
                        type="button"
                        :data-focus="`analysis:${entry.id}`"
                        :title="entry.name.value"
                        @click="openAnalysis(entry.id)"
                    >
                        <span :lang="entry.name.lang || undefined">{{
                            entry.name.value
                        }}</span>
                        <span
                            v-if="!entry.match"
                            class="visually-hidden"
                        >
                            {{ outsideText }}
                        </span>
                    </button>
                    <span
                        v-if="entry.unpublished"
                        class="badge draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>

        <section
            v-if="props.materials.length > 0"
            class="materials"
            :aria-labelledby="`${sectionId}-materials`"
        >
            <h4 :id="`${sectionId}-materials`">
                <span>{{ materialsTitle }}</span>
            </h4>
            <ul>
                <li
                    v-for="entry in props.materials"
                    :key="entry.id"
                    :class="{ 'is-dimmed': !entry.match }"
                >
                    <SelectionCheckbox
                        :item-key="characterizationKey(entry.id)"
                        :label="addLabel(entry.name.value)"
                        :held-label="removeLabel(entry.name.value)"
                        :hint="allHints.get(characterizationKey(entry.id))"
                    />
                    <button
                        type="button"
                        :data-focus="`characterization:${entry.id}`"
                        :title="entry.name.value"
                        @click="openMaterial(entry.id)"
                    >
                        <span
                            v-if="entry.swatch"
                            class="swatch"
                            aria-hidden="true"
                            :style="{ background: entry.swatch }"
                        ></span>
                        <span :lang="entry.name.lang || undefined">{{
                            entry.name.value
                        }}</span>
                        <span
                            v-if="!entry.match"
                            class="visually-hidden"
                        >
                            {{ outsideText }}
                        </span>
                    </button>
                    <span
                        v-if="entry.certainty"
                        class="badge certainty"
                        :lang="entry.certainty.lang"
                    >
                        {{ entry.certainty.value }}
                    </span>
                    <span
                        v-if="entry.unpublished"
                        class="badge draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </li>
            </ul>
        </section>
    </article>
</template>

<style scoped>
.component-card {
    display: grid;
    gap: 1rem;
}

.component-card .card-head {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    align-items: center;
}

.component-card .card-head .name {
    flex: 1 1 100%;
    font-weight: 600;
}

.component-card .card-head .icon-button {
    margin-inline-start: auto;
}

.component-card .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    color: var(--ink-muted);
}

.component-card .badge {
    padding: 0 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.75rem;
}

.component-card section {
    display: grid;
    gap: 0.5rem;
}

.component-card h4 {
    font-weight: 600;
}

.component-card .empty {
    color: var(--ink-muted);
}

.component-card ul {
    display: grid;
    gap: 0;
    padding: 0;
    list-style: none;
}

.component-card li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.component-card li.is-dimmed,
.component-card li.is-dimmed > button {
    color: var(--ink-muted);
}

.component-card li.is-dimmed > button::before {
    content: "";
    flex: none;
    inline-size: 0.5rem;
    block-size: 0.5rem;
    margin-inline-end: 0.5rem;
    border: 0.0625rem solid var(--ink-muted);
    border-radius: 50%;
}

.component-card .swatch {
    flex: none;
    inline-size: 0.75rem;
    block-size: 0.75rem;
    margin-inline-end: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 50%;
}

.component-card .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.component-card li > button {
    display: inline-flex;
    flex: 1 1 auto;
    align-items: center;
    justify-content: flex-start;
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

.component-card li > button:hover {
    background: var(--bg-alt);
}

.component-card li > button:focus-visible,
.component-card .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
