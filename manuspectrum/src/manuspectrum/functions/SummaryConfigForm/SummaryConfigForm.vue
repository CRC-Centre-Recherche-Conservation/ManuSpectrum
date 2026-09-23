<script setup lang="ts">
import { computed, nextTick, ref, watchEffect } from "vue";
import { useGettext } from "vue3-gettext";
import { useConfirm } from "primevue/useconfirm";

import Button from "primevue/button";
import ConfirmDialog from "primevue/confirmdialog";
import Message from "primevue/message";

import FieldRow from "@/manuspectrum/functions/SummaryConfigForm/components/FieldRow.vue";
import RollupEditor from "@/manuspectrum/functions/SummaryConfigForm/components/RollupEditor.vue";

import {
    ConfigConflictError,
    MAX_RELATED,
    blankHop,
    defaultStyleFor,
    emptyConfig,
    fetchConfig,
    fetchRelations,
    newRowUid,
    removeConfig,
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
    VersionedConfig,
} from "@/manuspectrum/functions/types.ts";

const DETACHED_EVENT = "detached" as const;
// PrimeVue's confirmation bus is shared by every Vue application of the page:
// the group keeps this dialog and another application's from answering each other.
const REMOVAL_GROUP = "summary-config-removal";

const { graphid } = defineProps<{ graphid: string }>();

const emit = defineEmits<{
    (event: typeof DETACHED_EVENT): void;
}>();

const { $gettext } = useGettext();
const confirm = useConfirm();

const config = ref<EditableConfig>(withRowUids(emptyConfig()));
const relations = ref<RelatableNodes | null>(null);
const warnings = ref<string[]>([]);
const errorMessage = ref("");
const errorDetail = ref("");
const loading = ref(true);
const saving = ref(false);
const removing = ref(false);
const saved = ref(false);
const attached = ref(true);
const conflicted = ref(false);
const etag = ref<string | null>(null);
const stateKnown = ref(false);
const formRoot = ref<HTMLElement | null>(null);

const aliasOptions = computed(() => relations.value?.fields ?? []);

watchEffect(() => {
    void load(graphid);
});

/**
 * Read both payloads at once; either failure leaves the form empty and says so.
 *
 * Until one read succeeds, the form offers no write: it never saves or removes
 * a state it has not read. A failed read after that keeps the ETag of the last
 * state read, so a later write stays conditional on it.
 */
async function load(id: string): Promise<void> {
    loading.value = true;
    clearFeedback();
    try {
        const [stored, relatable] = await Promise.all([
            fetchConfig(id),
            fetchRelations(id),
        ]);
        adopt(stored);
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
        adopt(await saveConfig(graphid, config.value, etag.value));
        saved.value = true;
        void revealFeedback();
    } catch (caught) {
        reportFailure(
            caught,
            $gettext("This configuration could not be saved."),
        );
    } finally {
        saving.value = false;
    }
}

function confirmRemoval(): void {
    confirm.require({
        group: REMOVAL_GROUP,
        header: $gettext("Remove this configuration"),
        message: $gettext(
            "Remove the summary configuration of this model? Its popups fall back to the name and the default popup. The page reloads afterwards; unsaved edits to other functions on this page ask for confirmation first.",
        ),
        acceptLabel: $gettext("Remove"),
        rejectLabel: $gettext("Cancel"),
        acceptProps: { "data-testid": "confirm-remove", severity: "danger" },
        rejectProps: { severity: "secondary" },
        accept: () => {
            void remove();
        },
    });
}

/**
 * Detach the function from the model, then report it to the shell.
 *
 * The function manager around the form listed the function as applied when
 * the page was drawn; the shell reloads the page on `detached` so it reads
 * that list again.
 */
async function remove(): Promise<void> {
    removing.value = true;
    clearFeedback();
    try {
        adopt(await removeConfig(graphid, etag.value));
        emit(DETACHED_EVENT);
    } catch (caught) {
        reportFailure(
            caught,
            $gettext("This configuration could not be removed."),
        );
    } finally {
        removing.value = false;
    }
}

/** Take a state the endpoint answered as the one the form edits. */
function adopt(stored: VersionedConfig): void {
    config.value = withRowUids(stored.config);
    warnings.value = stored.warnings;
    attached.value = stored.attached;
    etag.value = stored.etag;
    stateKnown.value = true;
}

/** A conflict says why and offers the reload; anything else shows its detail. */
function reportFailure(caught: unknown, message: string): void {
    if (caught instanceof ConfigConflictError) {
        conflicted.value = true;
        errorMessage.value = $gettext(
            "Someone else changed this configuration since you opened it. Your changes are not saved: reload it to see their version.",
        );
    } else {
        errorMessage.value = message;
        errorDetail.value = detailOf(caught);
    }
    void revealFeedback();
}

/**
 * Scroll the form back to its top, where the feedback of a write renders.
 *
 * The form scrolls on its own and its write buttons stick to its bottom edge,
 * away from that feedback. It assigns `scrollTop` because jsdom implements
 * neither `scrollTo` nor `scrollIntoView` on elements.
 */
async function revealFeedback(): Promise<void> {
    await nextTick();
    if (formRoot.value) {
        formRoot.value.scrollTop = 0;
    }
}

function clearFeedback(): void {
    errorMessage.value = "";
    errorDetail.value = "";
    saved.value = false;
    conflicted.value = false;
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
    <div
        ref="formRoot"
        class="summary-config"
    >
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
                <div class="failure">
                    <span>{{ errorMessage }}</span>
                    <span
                        v-if="errorDetail"
                        class="detail"
                    >
                        {{ errorDetail }}
                    </span>
                    <Button
                        v-if="conflicted || !stateKnown"
                        class="reload"
                        data-testid="reload-config"
                        icon="fa fa-refresh"
                        severity="secondary"
                        :label="$gettext('Reload the configuration')"
                        @click="load(graphid)"
                    />
                </div>
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
                    :disabled="removing || !stateKnown"
                    @click="save"
                />
                <Button
                    v-if="attached && stateKnown"
                    class="remove"
                    data-testid="remove-config"
                    icon="fa fa-trash"
                    severity="danger"
                    :label="$gettext('Remove this configuration')"
                    :loading="removing"
                    :disabled="saving || removing"
                    @click="confirmRemoval"
                />
            </div>
        </template>
        <ConfirmDialog :group="REMOVAL_GROUP" />
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

.summary-config .feedback .failure {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
}

.summary-config .feedback .detail {
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

.summary-config .actions .remove {
    margin-inline-start: auto;
}
</style>
