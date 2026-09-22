<script setup lang="ts">
import { computed, ref, watchEffect } from "vue";
import { useGettext } from "vue3-gettext";

import Button from "primevue/button";
import Message from "primevue/message";

import FieldRow from "@/manuspectrum/functions/SummaryConfigForm/components/FieldRow.vue";
import RollupEditor from "@/manuspectrum/functions/SummaryConfigForm/components/RollupEditor.vue";

import {
    MAX_RELATED,
    blankHop,
    defaultStyleFor,
    emptyConfig,
    fetchConfig,
    fetchRelations,
    newRowUid,
    saveConfig,
    withRowUids,
} from "@/manuspectrum/functions/summary-config-api.ts";

import type {
    EditableConfig,
    FieldStyle,
    LocalizedLabel,
    RelatableNodes,
    SummaryAggregate,
    SummaryField,
    SummaryHop,
    SummaryRollup,
} from "@/manuspectrum/functions/types.ts";

const { graphid } = defineProps<{ graphid: string }>();

const { $gettext } = useGettext();

const config = ref<EditableConfig>(withRowUids(emptyConfig()));
const relations = ref<RelatableNodes | null>(null);
const warnings = ref<string[]>([]);
const errorMessage = ref("");
const errorDetail = ref("");
const loading = ref(true);
const saving = ref(false);
const saved = ref(false);
const attached = ref(true);

const aliasOptions = computed(() => relations.value?.fields ?? []);

watchEffect(() => {
    void load(graphid);
});

/** Read both payloads at once; either failure leaves the form empty and says so. */
async function load(id: string): Promise<void> {
    loading.value = true;
    clearFeedback();
    try {
        const [stored, relatable] = await Promise.all([
            fetchConfig(id),
            fetchRelations(id),
        ]);
        config.value = withRowUids(stored.config);
        warnings.value = stored.warnings;
        attached.value = stored.attached;
        relations.value = relatable;
    } catch (caught) {
        config.value = withRowUids(emptyConfig());
        errorMessage.value = $gettext("This configuration could not be read.");
        errorDetail.value = detailOf(caught);
    } finally {
        loading.value = false;
    }
}

/**
 * Write the configuration and adopt what the endpoint stored.
 *
 * The answer is the cleaned configuration, so the form shows what was kept
 * rather than what was typed, and the warnings say what was dropped.
 */
async function save(): Promise<void> {
    saving.value = true;
    clearFeedback();
    try {
        const stored = await saveConfig(graphid, config.value);
        config.value = withRowUids(stored.config);
        warnings.value = stored.warnings;
        attached.value = stored.attached;
        saved.value = true;
    } catch (caught) {
        errorMessage.value = $gettext("This configuration could not be saved.");
        errorDetail.value = detailOf(caught);
    } finally {
        saving.value = false;
    }
}

function clearFeedback(): void {
    errorMessage.value = "";
    errorDetail.value = "";
    saved.value = false;
}

function detailOf(caught: unknown): string {
    return caught instanceof Error ? caught.message : String(caught);
}

/** An override no one filled is absent from the configuration, never blank. */
function withLabel(
    label: LocalizedLabel | undefined,
    language: "en" | "fr",
    text: string,
): LocalizedLabel | undefined {
    const merged: LocalizedLabel = { ...label, [language]: text };
    const kept = Object.entries(merged).filter(([, value]) => value);
    return kept.length ? Object.fromEntries(kept) : undefined;
}

function move<T>(entries: T[], index: number, offset: number): T[] {
    const target = index + offset;
    if (target < 0 || target >= entries.length) {
        return entries;
    }
    const moved = [...entries];
    [moved[index], moved[target]] = [moved[target], moved[index]];
    return moved;
}

function patchField(index: number, patch: Partial<SummaryField>): void {
    config.value.fields = config.value.fields.map((field, position) =>
        position === index ? { ...field, ...patch } : field,
    );
}

function addField(): void {
    const first = relations.value?.fields[0];
    config.value.fields = [
        ...config.value.fields,
        {
            uid: newRowUid(),
            alias: first?.alias ?? "",
            style: first ? defaultStyleFor(first.datatype) : "text",
        },
    ];
}

/** Choosing another node re-derives the style, as adding a field does. */
function setFieldAlias(index: number, alias: string): void {
    const chosen = relations.value?.fields.find(
        (field) => field.alias === alias,
    );
    patchField(index, {
        alias,
        style: chosen
            ? defaultStyleFor(chosen.datatype)
            : config.value.fields[index].style,
    });
}

function setFieldStyle(index: number, style: FieldStyle): void {
    patchField(index, { style });
}

function setFieldLabel(
    index: number,
    language: "en" | "fr",
    text: string,
): void {
    patchField(index, {
        label: withLabel(config.value.fields[index].label, language, text),
    });
}

function setFieldMaxValues(index: number, maxValues: number | null): void {
    patchField(index, { max_values: maxValues ?? undefined });
}

function removeField(index: number): void {
    config.value.fields = config.value.fields.filter(
        (_field, position) => position !== index,
    );
}

function moveField(index: number, offset: number): void {
    config.value.fields = move(config.value.fields, index, offset);
}

function patchRollup(index: number, patch: Partial<SummaryRollup>): void {
    config.value.rollups = config.value.rollups.map((rollup, position) =>
        position === index ? { ...rollup, ...patch } : rollup,
    );
}

function addRollup(): void {
    config.value.rollups = [
        ...config.value.rollups,
        {
            uid: newRowUid(),
            key: "",
            path: [blankHop(relations.value)],
            aggregate: [{ op: "count" }],
            max_related: MAX_RELATED,
        },
    ];
}

function setRollupLabel(
    index: number,
    language: "en" | "fr",
    text: string,
): void {
    patchRollup(index, {
        label: withLabel(config.value.rollups[index].label, language, text),
    });
}

function setRollupPath(index: number, path: SummaryHop[]): void {
    patchRollup(index, { path });
}

function setRollupAggregate(
    index: number,
    aggregate: SummaryAggregate[],
): void {
    patchRollup(index, { aggregate });
}

function removeRollup(index: number): void {
    config.value.rollups = config.value.rollups.filter(
        (_rollup, position) => position !== index,
    );
}
</script>

<template>
    <div class="summary-config">
        <p
            v-if="loading"
            class="loading"
            data-testid="config-loading"
        >
            {{ $gettext("Loading the configuration…") }}
        </p>
        <template v-else>
            <Message
                v-if="errorMessage"
                class="feedback"
                data-testid="config-error"
                severity="error"
                :closable="false"
            >
                <span>{{ errorMessage }}</span>
                <span class="detail">{{ errorDetail }}</span>
            </Message>
            <Message
                v-if="saved"
                class="feedback"
                data-testid="config-saved"
                severity="success"
                :closable="false"
            >
                <span>{{ $gettext("Configuration saved.") }}</span>
            </Message>
            <Message
                v-if="!attached"
                class="feedback"
                data-testid="config-unattached"
                severity="info"
                :closable="false"
            >
                <span>
                    {{
                        $gettext(
                            "This model has no summary configuration yet. Saving creates one.",
                        )
                    }}
                </span>
            </Message>
            <Message
                v-if="warnings.length"
                class="feedback"
                severity="warn"
                :closable="false"
            >
                <span>{{ $gettext("Some entries were dropped:") }}</span>
                <ul>
                    <li
                        v-for="warning in warnings"
                        :key="warning"
                        data-testid="config-warning"
                    >
                        {{ warning }}
                    </li>
                </ul>
            </Message>

            <section class="fields">
                <h4>{{ $gettext("Fields") }}</h4>
                <FieldRow
                    v-for="(field, index) in config.fields"
                    :key="field.uid"
                    :alias="field.alias"
                    :field-style="field.style"
                    :label-en="field.label?.en ?? ''"
                    :label-fr="field.label?.fr ?? ''"
                    :max-values="field.max_values ?? null"
                    :alias-options="aliasOptions"
                    :can-move-up="index > 0"
                    :can-move-down="index < config.fields.length - 1"
                    @update:alias="setFieldAlias(index, $event)"
                    @update:field-style="setFieldStyle(index, $event)"
                    @update:label-en="setFieldLabel(index, 'en', $event)"
                    @update:label-fr="setFieldLabel(index, 'fr', $event)"
                    @update:max-values="setFieldMaxValues(index, $event)"
                    @move-up="moveField(index, -1)"
                    @move-down="moveField(index, 1)"
                    @remove="removeField(index)"
                />
                <Button
                    class="add-field"
                    data-testid="add-field"
                    icon="fa fa-plus"
                    severity="secondary"
                    :label="$gettext('Add a field')"
                    @click="addField"
                />
            </section>

            <section class="rollups">
                <h4>{{ $gettext("Related counts") }}</h4>
                <RollupEditor
                    v-for="(rollup, index) in config.rollups"
                    :key="rollup.uid"
                    :rollup-key="rollup.key"
                    :label-en="rollup.label?.en ?? ''"
                    :label-fr="rollup.label?.fr ?? ''"
                    :path="rollup.path"
                    :aggregate="rollup.aggregate"
                    :max-related="rollup.max_related"
                    :relations="relations"
                    @update:rollup-key="patchRollup(index, { key: $event })"
                    @update:label-en="setRollupLabel(index, 'en', $event)"
                    @update:label-fr="setRollupLabel(index, 'fr', $event)"
                    @update:path="setRollupPath(index, $event)"
                    @update:aggregate="setRollupAggregate(index, $event)"
                    @update:max-related="
                        patchRollup(index, { max_related: $event })
                    "
                    @remove="removeRollup(index)"
                />
                <Button
                    class="add-rollup"
                    data-testid="add-rollup"
                    icon="fa fa-plus"
                    severity="secondary"
                    :label="$gettext('Add a related count')"
                    @click="addRollup"
                />
            </section>

            <div class="actions">
                <Button
                    class="save"
                    data-testid="save-config"
                    icon="fa fa-save"
                    :label="$gettext('Save this configuration')"
                    :loading="saving"
                    @click="save"
                />
            </div>
        </template>
    </div>
</template>

<style scoped>
/* The form scrolls on its own inside the Function Manager panel, and the
   action bar sticks to its bottom edge so the save button stays in view. */
.summary-config {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    max-height: calc(100vh - 24rem);
    padding: 1rem;
    overflow-y: auto;
    font-size: 1.2rem;
}

.summary-config h4 {
    font-size: 1.4rem;
    font-weight: 600;
    margin-block: 0 0.5rem;
    margin-inline: 0;
}

.summary-config .fields,
.summary-config .rollups {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.summary-config .feedback {
    display: block;
}

.summary-config .feedback .detail {
    display: block;
    font-family: monospace;
    opacity: 0.8;
}

.summary-config .actions {
    position: sticky;
    bottom: -1rem;
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
    margin: 0 -1rem -1rem;
    padding: 0.75rem 1rem;
    border-top: 0.1rem solid var(--p-content-border-color);
    background: var(--p-content-background);
}
</style>
