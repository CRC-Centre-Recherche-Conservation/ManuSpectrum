<script setup lang="ts">
import { computed, inject, nextTick, ref, useTemplateRef, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import Drawer from "primevue/drawer";
import RadioButton from "primevue/radiobutton";
import { useGettext } from "vue3-gettext";

import BusyStatus from "@/manuspectrum/pages/AnalysisExplorer/components/BusyStatus.vue";
import CitationBlock from "@/manuspectrum/pages/AnalysisExplorer/components/CitationBlock.vue";
import CopyButton from "@/manuspectrum/pages/AnalysisExplorer/components/CopyButton.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";

import { useShare } from "@/manuspectrum/pages/AnalysisExplorer/composables/useShare.ts";
import {
    formatSize,
    safeHref,
} from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { MIRADOR_URL_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { miradorLink } from "@/manuspectrum/pages/AnalysisExplorer/share/content-state.ts";
import {
    offeredScopes,
    shareQuery,
} from "@/manuspectrum/pages/AnalysisExplorer/share/scope.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { SELECTION_PARAM } from "@/manuspectrum/pages/AnalysisExplorer/store/selection-link.ts";

import type { OfferedScope } from "@/manuspectrum/pages/AnalysisExplorer/share/scope.ts";

const PHONE_QUERY = "(max-width: 30rem)";
const TITLE_ID = "share-title";
const SCOPE_INPUT = "share-scope";
const CITATIONS_FOLDED_AFTER = 3;

/**
 * « Share and export »: a button, shown when the view offers a scope (the
 * open document, the Selection, a project filtered alone), that opens a
 * drawer on the right (from the bottom on a phone) with three groups: Cite
 * (the availability statement, the share link, one citation per dataset
 * then per project of the analyses without one, the first three shown
 * until the reader asks for the others),
 * Data (spectra CSV, data package with its announced size, one package per
 * document over the export limit) and IIIF (manifest, Mirador when
 * `EXPLORER_MIRADOR_URL` is set). The share payload is asked only while the
 * drawer is open. A signed-in reader whose scope holds restricted items may
 * include them; the products then say so.
 */
const miradorUrl = inject(MIRADOR_URL_KEY, "");

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const phone = useMediaQuery(PHONE_QUERY);
const button = useTemplateRef<HTMLButtonElement>("button");
const lang = document.documentElement.lang || "en";

const open = ref(false);
const chosenKind = ref<OfferedScope["kind"] | null>(null);
/** The unrestricted query the reader asked restricted data for; any other scope is unrestricted. */
const restrictedFor = ref<string | null>(null);
/** The payload query whose citations are all shown. */
const unfoldedFor = ref<string | null>(null);
/** Restricted items of the default build, by its query. */
const restrictedCounts = ref(new Map<string, number>());

const offered = computed(() =>
    offeredScopes({
        view: store.view,
        screen: store.corpusScreen,
        document: store.document,
        basket: store.basket,
        filters: store.filters,
    }),
);
const scope = computed<OfferedScope | null>(
    () =>
        offered.value.find((option) => option.kind === chosenKind.value) ??
        offered.value[0] ??
        null,
);
const scopeQuery = computed(() =>
    scope.value ? shareQuery(scope.value).toString() : "",
);
const restricted = computed(
    () => scopeQuery.value !== "" && restrictedFor.value === scopeQuery.value,
);

const share = useShare(() => (open.value ? scope.value : null), restricted);

const failed = computed(
    () =>
        share.status.value === "unavailable" || share.status.value === "error",
);
const payload = computed(() => (failed.value ? null : share.data.value));
const restrictedCount = computed(
    () => restrictedCounts.value.get(scopeQuery.value) ?? 0,
);
const restrictedOffered = computed(
    () =>
        store.session.connected &&
        (restricted.value || restrictedCount.value > 0),
);
const citationsUnfolded = computed(
    () =>
        share.loaded.value !== null && unfoldedFor.value === share.loaded.value,
);
const shownCitations = computed(() => {
    const citations = payload.value?.citations ?? [];
    return citationsUnfolded.value
        ? citations
        : citations.slice(0, CITATIONS_FOLDED_AFTER);
});
const foldedCount = computed(
    () => (payload.value?.citations.length ?? 0) - shownCitations.value.length,
);
const packageSize = computed(() =>
    formatSize(payload.value?.export.bytes ?? null, lang),
);
const miradorHref = computed(() =>
    payload.value
        ? miradorLink(miradorUrl, { manifest: payload.value.links.manifest })
        : null,
);

watch(open, async (isOpen, wasOpen) => {
    if (isOpen || !wasOpen) return;
    await nextTick();
    button.value?.focus();
});

watch(
    () => share.data.value,
    (data) => {
        if (!data || data.scope.restricted) return;
        const counts = new Map(restrictedCounts.value);
        counts.set(share.loaded.value ?? "", data.scope.restrictedAvailable);
        restrictedCounts.value = counts;
    },
);

function show(): void {
    open.value = true;
}

function scopeLabel(option: OfferedScope): string {
    if (option.kind === "document") return $gettext("This document");
    if (option.kind === "project") return $gettext("This project");
    return interpolate(
        $gettext("My Selection (%{n})"),
        { n: option.keys.length },
        true,
    );
}

function chooseScope(kind: OfferedScope["kind"]): void {
    chosenKind.value = kind;
}

function unfoldCitations(): void {
    unfoldedFor.value = share.loaded.value;
}

function toggleRestricted(event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    restrictedFor.value = checked ? scopeQuery.value : null;
}

/** The address a reader shares: the page with the Selection's keys for a Selection, the page shown otherwise. */
function shareLink(): string {
    const current = scope.value;
    if (current?.kind !== "ids") return window.location.href;
    const url = new URL(window.location.pathname, window.location.origin);
    url.searchParams.set(SELECTION_PARAM, current.keys.join(","));
    return url.href;
}
</script>

<template>
    <div
        v-if="offered.length > 0"
        class="share-export"
    >
        <button
            ref="button"
            type="button"
            class="opener"
            aria-haspopup="dialog"
            :aria-expanded="open ? 'true' : 'false'"
            @click="show"
        >
            <span>{{ $gettext("Share and export") }}</span>
        </button>
        <Drawer
            v-model:visible="open"
            class="explorer-share-drawer"
            :position="phone ? 'bottom' : 'right'"
            :pt="{
                root: {
                    role: 'dialog',
                    'aria-labelledby': TITLE_ID,
                },
            }"
        >
            <section
                class="share-panel"
                :aria-labelledby="TITLE_ID"
                :aria-busy="share.status.value === 'loading' ? 'true' : 'false'"
            >
                <h3 :id="TITLE_ID">
                    <span>{{ $gettext("Share and export") }}</span>
                </h3>
                <fieldset
                    v-if="offered.length > 1"
                    class="scopes"
                >
                    <legend class="visually-hidden">
                        {{ $gettext("What to share") }}
                    </legend>
                    <div
                        v-for="option in offered"
                        :key="option.kind"
                        class="scope"
                    >
                        <RadioButton
                            :input-id="`${SCOPE_INPUT}-${option.kind}`"
                            :name="SCOPE_INPUT"
                            :value="option.kind"
                            :model-value="scope?.kind ?? null"
                            @update:model-value="chooseScope"
                        />
                        <label
                            class="choice"
                            :for="`${SCOPE_INPUT}-${option.kind}`"
                            >{{ scopeLabel(option) }}</label
                        >
                    </div>
                </fieldset>
                <BusyStatus
                    :busy="share.status.value === 'loading'"
                    :first="!payload"
                />
                <p
                    v-if="share.status.value === 'unavailable'"
                    class="gone"
                >
                    <span>{{
                        $gettext("These data are no longer available.")
                    }}</span>
                </p>
                <UnavailableState
                    v-else-if="share.status.value === 'error'"
                    status="error"
                    :hide-home="true"
                    @retry="share.retry"
                />
                <p
                    v-else-if="!payload"
                    class="loading ms-skeleton"
                ></p>
                <template v-else>
                    <p
                        v-if="
                            payload.scope.drafts > 0 || payload.scope.restricted
                        "
                        class="marks"
                    >
                        <span
                            v-if="payload.scope.drafts > 0"
                            class="badge"
                        >
                            {{
                                interpolate(
                                    $gettext("Contains drafts (%{n})"),
                                    { n: payload.scope.drafts },
                                    true,
                                )
                            }}
                        </span>
                        <span
                            v-if="payload.scope.restricted"
                            class="badge"
                        >
                            {{ $gettext("Contains restricted-access data") }}
                        </span>
                    </p>

                    <section
                        class="group"
                        aria-labelledby="share-cite"
                    >
                        <h4 id="share-cite">
                            <span>{{ $gettext("Cite") }}</span>
                        </h4>
                        <p class="availability">
                            <span>{{ payload.availability }}</span>
                        </p>
                        <div class="actions">
                            <CopyButton
                                :text="payload.availability"
                                :label="
                                    $gettext(
                                        'Copy the data availability statement',
                                    )
                                "
                            />
                            <CopyButton
                                :text="shareLink()"
                                :label="$gettext('Copy the share link')"
                            />
                        </div>
                        <CitationBlock
                            v-for="(citation, index) in shownCitations"
                            :key="index"
                            :citation="citation"
                        />
                        <button
                            v-if="foldedCount > 0"
                            type="button"
                            class="more"
                            @click="unfoldCitations"
                        >
                            <span>{{
                                interpolate(
                                    $ngettext(
                                        "Show the other citation",
                                        "Show the %{n} other citations",
                                        foldedCount,
                                    ),
                                    { n: foldedCount },
                                    true,
                                )
                            }}</span>
                        </button>
                    </section>

                    <section
                        class="group"
                        aria-labelledby="share-data"
                    >
                        <h4 id="share-data">
                            <span>{{ $gettext("Data") }}</span>
                        </h4>
                        <label
                            v-if="restrictedOffered"
                            class="restricted"
                        >
                            <input
                                type="checkbox"
                                :checked="restricted"
                                @change="toggleRestricted"
                            />
                            <span>
                                {{
                                    interpolate(
                                        $gettext(
                                            "Include restricted-access data (%{n})",
                                        ),
                                        { n: restrictedCount },
                                        true,
                                    )
                                }}
                            </span>
                        </label>
                        <ul class="downloads">
                            <li v-if="safeHref(payload.links.seriesCsv)">
                                <a
                                    class="series"
                                    download=""
                                    :href="safeHref(payload.links.seriesCsv)!"
                                >
                                    <span>{{ $gettext("Spectra (CSV)") }}</span>
                                </a>
                            </li>
                            <li
                                v-if="
                                    !payload.export.overLimit &&
                                    safeHref(payload.links.export)
                                "
                            >
                                <a
                                    class="package"
                                    download=""
                                    :href="safeHref(payload.links.export)!"
                                >
                                    <span>
                                        {{
                                            interpolate(
                                                $gettext(
                                                    "Data package (ZIP, %{size})",
                                                ),
                                                { size: packageSize },
                                                true,
                                            )
                                        }}
                                    </span>
                                </a>
                            </li>
                        </ul>
                        <template v-if="payload.export.overLimit">
                            <p class="limit">
                                <span
                                    v-if="payload.export.documents.length > 0"
                                >
                                    {{
                                        interpolate(
                                            $gettext(
                                                "This package (%{size}) is over the export limit: export one document at a time.",
                                            ),
                                            { size: packageSize },
                                            true,
                                        )
                                    }}
                                </span>
                                <span v-else>
                                    {{
                                        interpolate(
                                            $gettext(
                                                "This package (%{size}) is over the export limit.",
                                            ),
                                            { size: packageSize },
                                            true,
                                        )
                                    }}
                                </span>
                            </p>
                            <ul
                                v-if="payload.export.documents.length > 0"
                                class="documents"
                            >
                                <li
                                    v-for="part in payload.export.documents"
                                    :key="part.id"
                                >
                                    <a
                                        v-if="safeHref(part.url)"
                                        download=""
                                        :href="safeHref(part.url)!"
                                        :lang="part.name.lang"
                                    >
                                        <span>{{ part.name.value }}</span>
                                    </a>
                                </li>
                            </ul>
                        </template>
                    </section>

                    <section
                        class="group"
                        aria-labelledby="share-iiif"
                    >
                        <h4 id="share-iiif">
                            <span>{{ $gettext("IIIF") }}</span>
                        </h4>
                        <div class="actions">
                            <CopyButton
                                :text="payload.links.manifest"
                                :label="$gettext('Copy the manifest URL')"
                            />
                            <a
                                v-if="safeHref(payload.links.manifest)"
                                class="manifest external"
                                rel="noopener"
                                target="_blank"
                                :href="safeHref(payload.links.manifest)!"
                            >
                                <span>{{ $gettext("Open the manifest") }}</span>
                                <span class="visually-hidden">
                                    {{ $gettext("(new tab)") }}
                                </span>
                            </a>
                            <a
                                v-if="miradorHref"
                                class="mirador external"
                                rel="noopener"
                                target="_blank"
                                :href="miradorHref"
                            >
                                <span>{{ $gettext("Open in Mirador") }}</span>
                                <span class="visually-hidden">
                                    {{ $gettext("(new tab)") }}
                                </span>
                            </a>
                        </div>
                    </section>
                </template>
            </section>
        </Drawer>
    </div>
</template>

<style scoped>
.share-export .opener {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.875rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.share-export .opener:hover {
    border-color: var(--blue-text);
}

.share-export .opener:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.share-panel {
    display: grid;
    gap: 1rem;
}

.share-panel h3 {
    font-size: 0.9375rem;
    font-weight: 600;
}

.share-panel .scopes {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    padding: 0;
    border: 0;
}

.share-panel .scope {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
}

.share-panel .choice {
    cursor: pointer;
}

.share-panel .group {
    display: grid;
    gap: 0.5rem;
    padding-block-start: 0.75rem;
    border-block-start: 0.0625rem solid var(--border-hover);
}

.share-panel h4 {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.share-panel .marks {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
}

.share-panel .badge {
    padding-inline: 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.75rem;
}

.share-panel .availability,
.share-panel .limit,
.share-panel .gone {
    color: var(--ink-muted);
    font-size: 0.8125rem;
    overflow-wrap: anywhere;
}

.share-panel .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem;
}

.share-panel ul {
    display: grid;
    gap: 0.25rem;
    padding: 0;
    list-style: none;
}

.share-panel a {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    min-block-size: var(--explorer-target, 2.75rem);
    color: var(--blue-text);
}

.share-panel a:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.share-panel .external::after {
    content: "↗";
}

.share-panel .more {
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem dashed var(--border-hover);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    cursor: pointer;
}

.share-panel .more:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.share-panel .restricted {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    cursor: pointer;
}

.share-panel .loading {
    inline-size: 70%;
    block-size: 5rem;
}

.share-panel .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
