<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { componentNode } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { SelectionComponent } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/selection-components.ts";

const FOLIO_JOINER = ", ";

/**
 * The components of the Selection (`selectionComponents`), one toggle
 * chip each: its name, its folios and « analyses · identified materials »
 * counted, the legend of those counts after the last chip. A click pins
 * the component in the focus of Compare or unpins it (`comp:`); every
 * chip carries the focus marks (`useLinkedMarks().focus`, the `ms-focus`
 * ring, pip, bloom and preview). Nothing is shown without a component.
 * The chips wrap on narrow screens.
 */
const props = defineProps<{
    components: readonly SelectionComponent[];
}>();

const { $gettext, $ngettext, interpolate } = useGettext();
const marks = useLinkedMarks();

function folioText(component: SelectionComponent): string {
    return component.folios.join(FOLIO_JOINER);
}

function chipLabel(component: SelectionComponent): string {
    const analyses = interpolate(
        $ngettext("%{n} analysis", "%{n} analyses", component.analyses),
        { n: component.analyses },
        true,
    );
    const materials = interpolate(
        $ngettext(
            "%{n} identified material",
            "%{n} identified materials",
            component.materials,
        ),
        { n: component.materials },
        true,
    );
    if (component.folios.length === 0) {
        return interpolate(
            $gettext("%{name}: %{analyses}, %{materials}"),
            { name: component.name.value, analyses, materials },
            true,
        );
    }
    return interpolate(
        $gettext("%{name}, %{folios}: %{analyses}, %{materials}"),
        {
            name: component.name.value,
            folios: folioText(component),
            analyses,
            materials,
        },
        true,
    );
}
</script>

<template>
    <div
        v-if="props.components.length > 0"
        class="component-strip"
        role="group"
        :aria-label="$gettext('Components of the Selection')"
    >
        <span class="heading">{{ $gettext("Components") }}</span>
        <button
            v-for="component in props.components"
            :key="component.id"
            type="button"
            class="chip ms-focus"
            v-bind="marks.focus(componentNode(component.id))"
            :aria-label="chipLabel(component)"
            :aria-pressed="marks.pressed(componentNode(component.id))"
            @click="marks.toggle(componentNode(component.id))"
            @pointerenter="marks.enter(componentNode(component.id), $event)"
            @pointerleave="marks.leave($event)"
        >
            <FocusPip :node="componentNode(component.id)" />
            <span
                class="glyph"
                aria-hidden="true"
            ></span>
            <span
                class="name"
                :lang="component.name.lang"
                >{{ component.name.value }}</span
            >
            <span
                v-if="component.folios.length > 0"
                class="folios"
                >{{ folioText(component) }}</span
            >
            <span class="counts"
                >{{ component.analyses }} · {{ component.materials }}</span
            >
        </button>
        <span
            class="legend"
            aria-hidden="true"
            >{{ $gettext("analyses · identified materials") }}</span
        >
    </div>
</template>

<style scoped>
.component-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
    font-size: 0.8125rem;
}

.component-strip .heading {
    margin-inline-end: 0.25rem;
    color: var(--ink);
    font-weight: 600;
}

.component-strip .chip {
    --r: 999rem;
    --link-pip: 0.8125rem;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-block: 0;
    padding-inline: 0.625rem 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.component-strip .chip:hover {
    border-color: var(--ink-dim);
}

.component-strip .chip:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.1875rem;
}

.component-strip
    .chip:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 7%,
        var(--surface)
    );
}

.component-strip .chip[data-rel="none"] {
    border-color: var(--border);
}

.component-strip .glyph {
    flex: none;
    inline-size: 0.875rem;
    block-size: 0.875rem;
    border: 0.09375rem dashed var(--ink-dim);
    border-radius: 0.1875rem;
}

.component-strip .folios {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 400;
}

.component-strip .counts,
.component-strip .legend {
    color: var(--ink-muted);
    font-size: 0.75rem;
    font-weight: 400;
    font-variant-numeric: tabular-nums;
}
</style>
