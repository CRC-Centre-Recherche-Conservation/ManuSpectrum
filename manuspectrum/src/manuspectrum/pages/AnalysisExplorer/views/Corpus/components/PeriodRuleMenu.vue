<script setup lang="ts">
import { computed, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";

import { useMenuButton } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMenuButton.ts";

import type { PeriodMatch } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/**
 * The rule of the period filter (overlap or entirely within) in a « ⋯ » menu
 * button: a small control meant for the end of the facet's title line. It
 * emits `change` with the rule chosen, unless it is the one already held.
 */
const props = defineProps<{ match: PeriodMatch }>();
const emit = defineEmits<{ change: [match: PeriodMatch] }>();

const { $gettext } = useGettext();
const menuId = useId();
const ruleRoot = useTemplateRef<HTMLElement>("ruleRoot");
const ruleControl = useTemplateRef<InstanceType<typeof IconButton>>("rule");
const ruleElement = computed(() => ruleControl.value?.element ?? null);
const { expanded, closeMenu, toggle, onButtonKeydown, onMenuKeydown } =
    useMenuButton(ruleRoot, ruleElement);

const rules = computed<{ match: PeriodMatch; name: string; detail: string }[]>(
    () => [
        {
            match: "overlap",
            name: $gettext("Overlaps the period"),
            detail: $gettext("Keeps documents whose dates touch the period"),
        },
        {
            match: "within",
            name: $gettext("Entirely within the period"),
            detail: $gettext(
                "Keeps documents dated entirely inside the period",
            ),
        },
    ],
);

function chooseMatch(match: PeriodMatch): void {
    closeMenu(true);
    if (match !== props.match) emit("change", match);
}
</script>

<template>
    <div
        ref="ruleRoot"
        class="period-rule-menu"
    >
        <IconButton
            ref="rule"
            data-action="rule"
            icon="ellipsis-h"
            aria-haspopup="menu"
            :label="$gettext('Rule for the period')"
            :aria-expanded="expanded ? 'true' : 'false'"
            :aria-controls="expanded ? menuId : undefined"
            @click="toggle"
            @keydown="onButtonKeydown"
        />
        <ul
            v-if="expanded"
            :id="menuId"
            class="menu"
            role="menu"
            :aria-label="$gettext('Rule for the period')"
            @keydown="onMenuKeydown"
        >
            <li
                v-for="rule in rules"
                :key="rule.match"
                role="none"
            >
                <button
                    type="button"
                    role="menuitemradio"
                    tabindex="-1"
                    :data-match="rule.match"
                    :aria-checked="
                        props.match === rule.match ? 'true' : 'false'
                    "
                    @click="chooseMatch(rule.match)"
                >
                    <span class="rule-name">{{ rule.name }}</span>
                    <span class="rule-detail">{{ rule.detail }}</span>
                </button>
            </li>
        </ul>
    </div>
</template>

<style scoped>
.period-rule-menu {
    position: relative;
    flex: none;
}

.period-rule-menu .menu {
    position: absolute;
    z-index: 110;
    inset-block-start: 100%;
    inset-inline-end: 0;
    display: grid;
    inline-size: max-content;
    max-inline-size: min(18rem, 80vw);
    padding: 0.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: var(--shadow-md);
    list-style: none;
}

.period-rule-menu .menu button {
    display: grid;
    gap: 0.125rem;
    inline-size: 100%;
    min-block-size: var(--explorer-target, 2rem);
    padding: 0.25rem 0.5rem 0.25rem 1.5rem;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    text-align: start;
    cursor: pointer;
}

.period-rule-menu .menu button[aria-checked="true"] {
    position: relative;
    font-weight: 600;
}

.period-rule-menu .menu button[aria-checked="true"]::before {
    content: "✓";
    position: absolute;
    inset-inline-start: 0.5rem;
}

.period-rule-menu .menu button:hover,
.period-rule-menu .menu button:focus {
    background: var(--bg-alt);
}

.period-rule-menu .menu button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.125rem;
}

.period-rule-menu .rule-detail {
    color: var(--ink-muted);
    font-size: 0.6875rem;
    font-weight: 400;
}
</style>
