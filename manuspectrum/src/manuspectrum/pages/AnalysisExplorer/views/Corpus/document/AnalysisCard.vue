<script setup lang="ts">
import { computed, defineAsyncComponent } from "vue";
import { useGettext } from "vue3-gettext";

import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import AddToSelection from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/AddToSelection.vue";
import SafeHtml from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/SafeHtml.vue";

import {
    formatDateRange,
    formatSize,
    safeHref,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import {
    entryKeyOf,
    fileKey,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/entries.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { viewerFor } from "@/manuspectrum/pages/AnalysisExplorer/viewers/registry.ts";

import type { Component } from "vue";

import type {
    AnalysisPayload,
    FileEntry,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RequestHandle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";

interface ConditionGroup {
    title: Label;
    items: { html: string; lang: string }[];
}

const COPYRIGHT = "©";

const props = defineProps<{ handle: RequestHandle<AnalysisPayload> }>();

const emit = defineEmits<{ close: [] }>();

const store = useExplorerStore();
const { $gettext } = useGettext();
const lang = document.documentElement.lang || "en";

const previews = new Map<string, Component>();

const analysis = computed(() => props.handle.data.value);
const status = computed(() => props.handle.status.value);
const failed = computed(
    () => status.value === "unavailable" || status.value === "error",
);
const files = computed(() => analysis.value?.files ?? []);
const byId = computed(
    () => new Map(files.value.map((file) => [file.id, file])),
);
const readable = computed(() =>
    files.value.filter((file) => file.role === "readable"),
);
const notInChart = computed(() =>
    files.value.filter(
        (file) =>
            (file.role === "raw" && !file.pairedWith) ||
            (file.role === "other" && file.dataKind === "file"),
    ),
);
/** One preview per spectrum axis set (the first file stands for its set), then every other file a viewer shows. */
const previewed = computed<FileEntry[]>(() => {
    const seenAxes = new Set<string>();
    const shown: FileEntry[] = [];
    for (const file of files.value) {
        if (file.dataKind === "xy" && file.role === "readable") {
            const axes = file.viewer.axisKey ?? file.id;
            if (seenAxes.has(axes)) continue;
            seenAxes.add(axes);
            shown.push(file);
        } else if (file.dataKind !== "xy" && file.dataKind !== "file") {
            shown.push(file);
        } else if (viewerFor(file.dataKind).external) {
            shown.push(file);
        }
    }
    return shown;
});
const entryKey = computed(() =>
    analysis.value ? entryKeyOf(analysis.value) : null,
);
const conditionGroups = computed<ConditionGroup[]>(() => {
    const groups = new Map<string, ConditionGroup>();
    for (const condition of analysis.value?.conditions ?? []) {
        const key = condition.type?.uri ?? "";
        const title = condition.type?.label ?? {
            value: $gettext("Note"),
            lang: "",
        };
        const group = groups.get(key) ?? { title, items: [] };
        group.items.push({ html: condition.html, lang: condition.lang });
        groups.set(key, group);
    }
    return [...groups.values()];
});
const date = computed(() =>
    analysis.value ? formatDateRange(analysis.value.date) : "",
);
const datasetHref = computed(() => safeHref(analysis.value?.dataset?.url));
const licence = computed(
    () => previewed.value[0]?.license ?? files.value[0]?.license ?? null,
);
const licenceHref = computed(() => safeHref(licence.value?.url));
const attribution = computed(() => {
    const text = licence.value?.attribution;
    if (!text) return "";
    return text.startsWith(COPYRIGHT) ? text : `${COPYRIGHT} ${text}`;
});
const permalink = computed(() => safeHref(analysis.value?.permalink));

function previewOf(file: FileEntry): Component {
    const entry = viewerFor(file.dataKind);
    let preview = previews.get(entry.kind);
    if (!preview) {
        preview = defineAsyncComponent(entry.preview);
        previews.set(entry.kind, preview);
    }
    return preview;
}

function rawOf(file: FileEntry): FileEntry | null {
    return file.pairedWith ? byId.value.get(file.pairedWith) ?? null : null;
}

function rawLabel(file: FileEntry): string {
    const extension = file.name.includes(".")
        ? `.${file.name.split(".").pop()}`
        : file.format;
    return [$gettext("raw instrument"), extension, formatSize(file.size, lang)]
        .filter(Boolean)
        .join(" · ");
}

function names(refs: { name: Label }[]): string {
    return refs.map((ref) => ref.name.value).join(", ");
}

function close(): void {
    emit("close");
}

function openCharacterization(id: string): void {
    store.focusOn({ kind: "characterization", id });
}
</script>

<template>
    <article
        class="analysis-card"
        :aria-busy="status === 'loading' ? 'true' : 'false'"
    >
        <UnavailableState
            v-if="failed"
            :status="status === 'unavailable' ? 'unavailable' : 'error'"
            :hide-home="true"
            @retry="props.handle.retry"
        />
        <template v-else-if="analysis">
            <header class="card-head">
                <h3
                    class="name"
                    tabindex="-1"
                    :lang="analysis.name.lang"
                >
                    <span>{{ analysis.name.value }}</span>
                </h3>
                <p class="meta">
                    <span
                        v-if="analysis.technique"
                        :lang="analysis.technique.label.lang"
                    >
                        {{ analysis.technique.label.value }}
                    </span>
                    <span
                        v-if="analysis.unpublished"
                        class="badge draft"
                    >
                        {{ $gettext("Draft") }}
                    </span>
                </p>
                <AddToSelection
                    v-if="entryKey"
                    :keys="[entryKey]"
                    :label="$gettext('+ Selection')"
                />
                <button
                    type="button"
                    class="close"
                    @click="close"
                >
                    <span>{{ $gettext("Close") }}</span>
                </button>
            </header>

            <section
                v-if="previewed.length > 0"
                class="preview"
                :aria-label="$gettext('Preview')"
            >
                <component
                    :is="previewOf(file)"
                    v-for="file in previewed"
                    :key="file.id"
                    :file="file"
                    :analysis="analysis"
                />
            </section>

            <section
                v-if="readable.length > 0"
                class="files"
                aria-labelledby="card-files"
            >
                <h4 id="card-files">
                    <span>{{ $gettext("Files") }}</span>
                </h4>
                <ul>
                    <li
                        v-for="file in readable"
                        :key="file.id"
                        :data-file="file.id"
                    >
                        <a
                            v-if="safeHref(file.downloadUrl)"
                            class="file-name"
                            download=""
                            :href="safeHref(file.downloadUrl)!"
                        >
                            <span>{{ file.name }}</span>
                        </a>
                        <span
                            v-else
                            class="file-name"
                        >
                            {{ file.name }}
                        </span>
                        <template v-if="rawOf(file)">
                            <a
                                v-if="safeHref(rawOf(file)!.downloadUrl)"
                                class="raw"
                                download=""
                                :href="safeHref(rawOf(file)!.downloadUrl)!"
                            >
                                <span>{{ rawLabel(rawOf(file)!) }}</span>
                            </a>
                            <span
                                v-else
                                class="raw"
                            >
                                {{ rawLabel(rawOf(file)!) }}
                            </span>
                        </template>
                        <AddToSelection
                            :keys="[fileKey(analysis.id, file.id)]"
                            :label="$gettext('+ Selection')"
                        />
                    </li>
                </ul>
            </section>

            <section
                v-if="notInChart.length > 0"
                class="not-in-chart"
                aria-labelledby="card-not-in-chart"
            >
                <h4 id="card-not-in-chart">
                    <span>{{ $gettext("Not in a chart") }}</span>
                </h4>
                <ul>
                    <li
                        v-for="file in notInChart"
                        :key="file.id"
                    >
                        <span>{{ file.name }}</span>
                        <a
                            v-if="safeHref(file.downloadUrl)"
                            download=""
                            :href="safeHref(file.downloadUrl)!"
                        >
                            <span>
                                {{
                                    file.role === "raw"
                                        ? $gettext("Download the raw file")
                                        : $gettext("Download the file")
                                }}
                            </span>
                        </a>
                    </li>
                </ul>
            </section>

            <section
                class="conditions"
                aria-labelledby="card-conditions"
            >
                <h4 id="card-conditions">
                    <span>{{ $gettext("Measurement conditions") }}</span>
                </h4>
                <p
                    v-if="conditionGroups.length === 0"
                    class="empty"
                >
                    <span>{{ $gettext("Not provided") }}</span>
                </p>
                <dl v-else>
                    <template
                        v-for="group in conditionGroups"
                        :key="group.title.value"
                    >
                        <dt :lang="group.title.lang || undefined">
                            <span>{{ group.title.value }}</span>
                        </dt>
                        <dd
                            v-for="(item, index) in group.items"
                            :key="index"
                        >
                            <SafeHtml
                                :html="item.html"
                                :lang="item.lang"
                            />
                        </dd>
                    </template>
                </dl>
            </section>

            <dl class="details">
                <template v-if="analysis.instrument">
                    <dt>
                        <span>{{ $gettext("Instrument") }}</span>
                    </dt>
                    <dd :lang="analysis.instrument.name.lang">
                        <span>{{ analysis.instrument.name.value }}</span>
                    </dd>
                </template>
                <template v-if="analysis.operators.length > 0">
                    <dt>
                        <span>{{ $gettext("Operators") }}</span>
                    </dt>
                    <dd>
                        <span>{{ names(analysis.operators) }}</span>
                    </dd>
                </template>
                <template v-if="analysis.projects.length > 0">
                    <dt>
                        <span>{{ $gettext("Projects") }}</span>
                    </dt>
                    <dd>
                        <span>{{ names(analysis.projects) }}</span>
                    </dd>
                </template>
                <template v-if="date">
                    <dt>
                        <span>{{ $gettext("Date") }}</span>
                    </dt>
                    <dd>
                        <span>{{ date }}</span>
                    </dd>
                </template>
                <template v-if="analysis.component">
                    <dt>
                        <span>{{ $gettext("Studied area") }}</span>
                    </dt>
                    <dd :lang="analysis.component.name.lang">
                        <span>{{ analysis.component.name.value }}</span>
                    </dd>
                </template>
                <template v-if="analysis.sample">
                    <dt>
                        <span>{{ $gettext("Sample") }}</span>
                    </dt>
                    <dd :lang="analysis.sample.name.lang">
                        <span>{{ analysis.sample.name.value }}</span>
                    </dd>
                </template>
                <template v-if="analysis.dataset">
                    <dt>
                        <span>{{ $gettext("Dataset") }}</span>
                    </dt>
                    <dd>
                        <a
                            v-if="datasetHref"
                            rel="noopener"
                            target="_blank"
                            :href="datasetHref"
                        >
                            <span>
                                {{
                                    analysis.dataset.label ||
                                    analysis.dataset.url
                                }}
                            </span>
                        </a>
                        <span v-else>
                            {{ analysis.dataset.label || analysis.dataset.url }}
                        </span>
                        <span
                            v-if="analysis.dataset.isDoi"
                            class="badge doi"
                        >
                            {{ $gettext("DOI") }}
                        </span>
                    </dd>
                </template>
                <template v-if="analysis.bibliography.length > 0">
                    <dt>
                        <span>{{ $gettext("Bibliography") }}</span>
                    </dt>
                    <dd
                        v-for="(entry, index) in analysis.bibliography"
                        :key="index"
                        :lang="entry.lang"
                    >
                        <span>{{ entry.value }}</span>
                    </dd>
                </template>
            </dl>

            <p
                v-if="licence"
                class="licence"
            >
                <span>{{ $gettext("Licence") }}</span>
                <a
                    v-if="licenceHref"
                    rel="noopener license"
                    target="_blank"
                    :href="licenceHref"
                    :lang="licence.label.lang"
                >
                    <span>{{ licence.label.value }}</span>
                </a>
                <span
                    v-else
                    :lang="licence.label.lang"
                >
                    {{ licence.label.value }}
                </span>
                <span
                    v-if="licence.isDefault"
                    class="badge default"
                >
                    {{ $gettext("default licence") }}
                </span>
                <span
                    v-if="attribution"
                    class="attribution"
                >
                    {{ attribution }}
                </span>
            </p>

            <section
                v-if="analysis.evidenceOf.length > 0"
                class="evidence-of"
                aria-labelledby="card-evidence-of"
            >
                <h4 id="card-evidence-of">
                    <span>{{ $gettext("Supporting analysis of") }}</span>
                </h4>
                <ul>
                    <li
                        v-for="summary in analysis.evidenceOf"
                        :key="summary.id"
                    >
                        <button
                            type="button"
                            :lang="summary.name.lang"
                            @click="openCharacterization(summary.id)"
                        >
                            <span>{{ summary.name.value }}</span>
                        </button>
                    </li>
                </ul>
            </section>

            <a
                v-if="permalink"
                class="record"
                :href="permalink"
            >
                <span>{{ $gettext("Full record") }}</span>
            </a>
        </template>
    </article>
</template>

<style scoped>
.analysis-card {
    display: grid;
    gap: 1rem;
    container-type: inline-size;
}

.analysis-card .card-head {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    align-items: center;
}

.analysis-card .card-head .name {
    flex: 1 1 100%;
    font-weight: 600;
}

.analysis-card .card-head .close {
    margin-inline-start: auto;
}

.analysis-card .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    color: var(--ink-muted);
}

.analysis-card h4,
.analysis-card dt {
    font-weight: 600;
}

.analysis-card .badge {
    padding: 0 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.75rem;
}

.analysis-card .preview,
.analysis-card section {
    display: grid;
    gap: 0.5rem;
}

.analysis-card ul {
    display: grid;
    gap: 0.5rem;
    padding: 0;
    list-style: none;
}

.analysis-card .files li,
.analysis-card .not-in-chart li,
.analysis-card .licence {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    align-items: center;
}

.analysis-card a,
.analysis-card button {
    display: inline-flex;
    align-items: center;
    min-block-size: 2.75rem;
}

.analysis-card a {
    color: var(--blue-text);
}

.analysis-card .card-head .close,
.analysis-card .evidence-of button {
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.analysis-card a:focus-visible,
.analysis-card button:focus-visible,
.analysis-card .name:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.analysis-card .raw,
.analysis-card .empty,
.analysis-card .attribution {
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.analysis-card dl {
    display: grid;
    grid-template-columns: minmax(8rem, auto) 1fr;
    gap: 0.25rem 1rem;
}

.analysis-card dd {
    grid-column: 2;
}

@container (max-width: 30rem) {
    .analysis-card dl {
        grid-template-columns: 1fr;
    }

    .analysis-card dd {
        grid-column: 1;
    }
}
</style>
