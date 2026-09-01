// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science


import $ from 'jquery';
import arches from 'arches';
import ko from 'knockout';
import afsReaderTemplate from 'templates/views/components/cards/file-renderers/xy-reader.htm';
import AfsInstrumentViewModel from 'viewmodels/afs-instrument';
import Cookies from 'js-cookie';
import XyParser from 'utils/xy-parser';
import {
    TRANSFORM_ANNOTATION_KEYS,
    TRANSFORM_TRANSLATION_KEYS,
    applyTransforms,
    deriveAxisLabel,
    deriveXAxisLabel,
    describeChain,
    expandStoredConfig,
    seriesRoles,
} from 'utils/xy-transforms';
import dispose from 'utils/dispose';
import { getRendererConfig, invalidate, parseOverrides } from 'utils/renderer-cache';
import 'bindings/plotly';
import 'views/components/plugins/importer-configuration';

// Mirrors CONFIG_SOURCE_* in manuspectrum/constants/xy_presets.py. Written on
// every entry a curator configures by hand, so the "auto" badge in the file
// lists tells the truth about where a configuration came from — and so the
// technique mapping knows a human has spoken and leaves the entry alone.

// Transform key -> the sentence a reader sees. Resolved here, not in
// utils/xy-transforms.js, so that module stays importable without a page and
// its specs need no translation bundle. Same split as VIEW_LABELS below.
const stepLabels = () =>
    Object.fromEntries(
        Object.entries(TRANSFORM_TRANSLATION_KEYS).map(([step, key]) => [
            step,
            arches.translations[key] || step,
        ])
    );

// The terser wording the axis puts in brackets. Untranslated keys are dropped
// rather than defaulted, so deriveAxisLabel falls back to its English
// annotation instead of printing a machine key on the chart.
const annotationLabels = () =>
    Object.fromEntries(
        Object.entries(TRANSFORM_ANNOTATION_KEYS)
            .map(([step, key]) => [step, arches.translations[key]])
            .filter(([, label]) => label)
    );

// The word a caption puts before a Savitzky-Golay window size.
const windowWord = () => arches.translations.xyStepWindow;

const CONFIG_SOURCE_MANUAL = 'manual';

export default ko.components.register('xy-reader', {
    viewModel: function (params) {
        const self = this;
        this.alert = params?.pageVm?.alert;
        this.showConfigAdd = ko.observable(false);
        this.configName = ko.observable();
        this.delimiterCharacter = ko.observable();
        this.invalidDelimiter = ko.observable(false);
        this.headerDelimiter = ko.observable();
        this.headerFixedLines = ko.observable();
        this.selectedConfig = params.selectedConfig || ko.observable();
        this.selectedFile = params.selectedFile || ko.observable();
        this.selectedConfiguration = undefined;
        AfsInstrumentViewModel.apply(this, [params]);
        this.disposables = [];

        // One file per tile is the rule here: Arches' file workbench creates a
        // fresh tile per dropped file, and its getUrl() only reads a tile whose
        // value holds exactly one entry. An instrument's original and its CSV
        // derivative therefore live in sibling tiles, not together.
        //
        // The node still permits several files (`maxFiles`), and the card form
        // can write them, so resolve the entry this renderer owns instead of
        // trusting position. Falls back to the first entry so a tile whose file
        // has no renderer yet still reports itself — that is what drives the
        // "No config" warnings.
        const xyEntry = (node) => {
            if (!node || !node.length) return null;
            return (
                node.find(
                    (entry) => ko.unwrap(entry?.renderer) === self.renderer
                ) || node[0]
            );
        };
        this.xyEntry = xyEntry;

        // set defaults for chart title/axis
        this.chartTitle(arches.translations.data);
        this.xAxisLabel(arches.translations.xAxis);
        this.yAxisLabel(arches.translations.yAxis);
        // Both of these belong to the SHARED state, not to this instance.
        //
        // Arches builds a file renderer twice per displayed file — once for the
        // chart (`context: 'render'`) and once for the side panel that hosts the
        // configuration picker (`context: 'tab-contents'`); see
        // arches/app/templates/views/components/file-workbench.htm. The two
        // instances only ever meet through `params.state`, the single object
        // Arches hangs off each entry of `fileFormatRenderers`, and
        // AfsInstrumentViewModel already puts every other chart setting there.
        //
        // Declared on `this` these were private per instance, so picking a
        // configuration in the panel moved the panel's own copy while the chart
        // kept the axis direction and processing note of whatever it had loaded
        // with — the labels changed, the FTIR axis stayed ascending, and only a
        // reload put it right.
        if ('xReversed' in this.commonData === false) {
            // Descending X axis, as FTIR, NMR and XPS are conventionally plotted.
            this.commonData.xReversed = ko.observable(false);
            // What the configuration applied, stated under the chart.
            this.commonData.processing = ko.observable(null);
        }
        this.xReversed = this.commonData.xReversed;
        this.processing = this.commonData.processing;

        this.rendererConfigs = ko.observable([]);

        // on init, get available renderer configs for display to user.
        const rendererConfigRefresh = async () => {
            try {
                const renderers = await getRendererConfig(self.renderer);
                const configs = renderers?.configs;
                this.rendererConfigs(configs);
                const displayContent =
                    self.fileViewer?.displayContent() ||
                    self.displayContent;
                if (displayContent) {
                    const tile = displayContent.tile;

                    // displayContent is formatted differently from the core file viewer.
                    const configId = tile
                        ? xyEntry(
                              ko.unwrap(
                                  tile.data[self.fileViewer.fileListNodeId]
                              )
                          )?.rendererConfig
                        : displayContent?.rendererConfig;

                    if (configId) {
                        this.selectedConfig(ko.unwrap(configId));
                    }
                }
            } catch {
                // fetch failed, leave configs empty
            }
        };

        // Fan the configuration now in `selectedConfiguration` out over
        // everything the chart reads.
        //
        // Two paths change what is plotted — picking a different configuration,
        // and saving an edit to the one already picked — and each used to carry
        // its own copy of this list. The copies drifted: the save path never
        // touched the reversed axis or the processing note, and derived the Y
        // label from the stored string instead of from the applied chain. One
        // list, called from both.
        const applyDisplayConfig = () => {
            const config = self.selectedConfiguration?.config;
            const display = config?.display;
            const expanded = expandStoredConfig(config);

            // Read back by parse() on the next render.
            self._columnAssignments = display?.columnAssignments || null;
            self._xColumnMode = config?.xColumnMode || null;

            self.chartTitle(display?.chartTitle || arches.translations.data);
            self.xAxisLabel(
                deriveXAxisLabel(
                    display?.xAxisLabel || arches.translations.xAxis,
                    config,
                    arches.translations.xAxisPoint
                )
            );
            // Derived, never the stored string on its own: the label has to
            // follow what is actually plotted.
            self.yAxisLabel(
                display?.yAxisLabel
                    ? deriveAxisLabel(
                          display.yAxisLabel,
                          expanded,
                          annotationLabels()
                      )
                    : arches.translations.yAxis
            );
            self.yAxisRightLabel(display?.yAxisRightLabel || '');
            self.xReversed(!!display?.xReversed);
            self.processing(describeChain(expanded, stepLabels(), windowWord()));
        };

        this.disposables.push(this.selectedConfig.subscribe((config) => {
            if (
                !config ||
                (this.selectedFile() &&
                    this.selectedFile().url !== this.displayContent.url)
            ) {
                return;
            }
            this.selectedConfiguration = this.rendererConfigs().find(
                (currentConfig) => {
                    return currentConfig.configid === config;
                }
            );
            // Picking a configuration PREVIEWS it — it does not commit it.
            // Choosing one used to write and save it straight onto whichever
            // file happened to be on screen, so a curator comparing options
            // silently rewrote the file they were only looking at, and had no
            // way to back out. Committing is now one deliberate act: select the
            // files, pick a configuration, press the button.
            //
            // Settled before rendering: parse() reads the column roles and the
            // spectral range this just wrote.
            applyDisplayConfig();
            self.render();
        }));

        rendererConfigRefresh();

        // Rename the core "Edit" tab to "Viz".
        //
        // The tab belongs to Arches' own file-viewer template, so relabelling it
        // means reaching into the DOM. Knockout re-renders that strip whenever
        // the displayed file changes, which silently undid a one-shot rename and
        // left the tab reading "Edit" again with a pencil icon — so re-apply on
        // every change rather than once at construction.
        const renameEditTab = () => {
            setTimeout(() => {
                $('.workbench-card-sidebar-tab').each(function () {
                    const bind = $(this).attr('data-bind') || '';
                    if (bind.includes("toggleTab('edit')")) {
                        $(this)
                            .find('i.fa')
                            .removeClass('fa-pencil')
                            .addClass('fa-eye');
                        $(this)
                            .find('.map-sidebar-text')
                            .text(arches.translations.xyVizTab);
                    }
                });
            }, 0);
        };
        renameEditTab();
        if (ko.isObservable(this.fileViewer?.displayContent)) {
            this.disposables.push(
                this.fileViewer.displayContent.subscribe(renameEditTab)
            );
        }

        // Track whether the importer-configuration child is showing its list (not the edit panel)
        this.importerShowingList = ko.observable(true);

        // --- Batch apply config to staged tiles ---
        this.batchApplying = ko.observable(false);
        this.batchResult = ko.observable('');

        this.stagedXyTileCount = ko.pureComputed(() => {
            const card = self.fileViewer?.card;
            if (!card || !card.staging) return 0;
            const stagingIds = card.staging();
            if (!stagingIds.length) return 0;
            const tiles = card.tiles();
            let count = 0;
            stagingIds.forEach((tileid) => {
                const tile = tiles.find((t) => t.tileid == tileid);
                if (tile) {
                    const node = ko.unwrap(
                        tile.data[self.fileViewer.fileListNodeId]
                    );
                    if (
                        ko.unwrap(xyEntry(node)?.renderer) === self.renderer
                    ) {
                        count++;
                    }
                }
            });
            return count;
        });

        this.batchMode = ko.pureComputed(
            () => self.stagedXyTileCount() > 0
        );

        // How many selected files the chosen configuration would actually
        // change. A freshly created resource arrives with its file already
        // configured from the technique, and the panel pre-selects that same
        // configuration — so the old count offered to apply what was already
        // applied, and the button never had anything to do.
        // Bumped after a batch runs. Tile data is mutated in place — plain
        // properties on plain objects — so nothing would otherwise tell this
        // count to re-evaluate, and the button would sit there claiming work
        // remained. Clearing the selection instead would have worked, but it
        // throws away a selection the curator may still want: after applying
        // one configuration they often try another on the same files.
        const batchVersion = ko.observable(0);

        // What "apply" acts on.
        //
        // Ticking files and viewing one are two different things in Arches:
        // `card.staging()` is the checkbox list, while `displayContent` derives
        // from `tile.selected()`. Opening a file does not tick it. So a curator
        // looking at a single spectrum has nothing staged, and a count based on
        // staging alone left them no way to commit a configuration change — the
        // button simply never appeared.
        //
        // Ticked files win when there are any; otherwise the file on screen is
        // the obvious subject.
        const batchTiles = () => {
            const card = self.fileViewer?.card;
            if (!card) return [];
            const tiles = card.tiles();
            const stagingIds = card.staging ? card.staging() : [];
            if (stagingIds.length) {
                return stagingIds
                    .map((tileid) => tiles.find((t) => t.tileid == tileid))
                    .filter(Boolean);
            }
            const displayed = self.fileViewer.displayContent();
            return displayed?.tile ? [displayed.tile] : [];
        };

        const xyEntryOf = (tile) =>
            xyEntry(ko.unwrap(tile.data[self.fileViewer.fileListNodeId]));

        this.pendingBatchCount = ko.pureComputed(() => {
            batchVersion();
            const configId = self.selectedConfig();
            if (!configId) return 0;
            return batchTiles().filter((tile) => {
                const entry = xyEntryOf(tile);
                if (ko.unwrap(entry?.renderer) !== self.renderer) return false;
                return ko.unwrap(entry.rendererConfig) !== configId;
            }).length;
        });

        this.canApplyBatch = ko.pureComputed(
            () => self.pendingBatchCount() > 0
        );

        this.applyConfigToStaged = async () => {
            const card = self.fileViewer?.card;
            if (!card || !card.staging) return;

            const configId = self.selectedConfig();
            if (!configId) return;

            self.batchApplying(true);
            self.batchResult('');

            let applied = 0;
            let errors = 0;

            for (const tile of batchTiles()) {
                const entry = xyEntryOf(tile);
                if (ko.unwrap(entry?.renderer) !== self.renderer) {
                    continue;
                }
                try {
                    entry.rendererConfig = configId;
                    entry.rendererConfigSource = CONFIG_SOURCE_MANUAL;
                    await tile.save();
                    applied++;
                } catch (e) {
                    console.error('Batch config save error:', tile.tileid, e);
                    errors++;
                }
            }

            self.batchApplying(false);
            if (applied > 0) {
                // Re-evaluate against the configurations just written; the
                // selection itself is left alone.
                batchVersion(batchVersion() + 1);
            }
            if (errors > 0) {
                self.batchResult(
                    applied +
                        ' applied, ' +
                        errors +
                        ' error(s)'
                );
            } else {
                self.batchResult(
                    'Config applied to ' + applied + ' file(s)'
                );
            }

            setTimeout(() => {
                self.batchResult('');
            }, 5000);
        };

        // --- Feature 1: Staged XY files with config status ---
        this.stagedXyFiles = ko.pureComputed(() => {
            const card = self.fileViewer?.card;
            if (!card || !card.staging) return [];
            const stagingIds = card.staging();
            const tiles = card.tiles();
            const configs = self.rendererConfigs();
            return stagingIds
                .map((tileid) => {
                    const tile = tiles.find((t) => t.tileid == tileid);
                    if (!tile) return null;
                    const node = ko.unwrap(
                        tile.data[self.fileViewer.fileListNodeId]
                    );
                    const entry = xyEntry(node);
                    if (ko.unwrap(entry?.renderer) !== self.renderer)
                        return null;
                    const configId = ko.unwrap(entry.rendererConfig);
                    const cfg = configs.find(
                        (c) => c.configid === configId
                    );
                    return {
                        name: ko.unwrap(entry.name) || 'Unknown',
                        hasConfig: !!configId,
                        configName: cfg?.name || null,
                        // Surfaced in the UI so a deduced configuration never
                        // passes for a deliberate one: an analysis tagged with
                        // the wrong technique would otherwise hand a plausible
                        // but wrong axis label to whoever reads the spectrum.
                        isAutoConfig:
                            ko.unwrap(entry.rendererConfigSource) === 'auto',
                        tileid: tileid,
                    };
                })
                .filter(Boolean);
        });

        // --- Feature 4: All XY files overview ---
        this.allXyFiles = ko.pureComputed(() => {
            const card = self.fileViewer?.card;
            if (!card) return [];
            const tiles = card.tiles();
            const configs = self.rendererConfigs();
            return tiles
                .map((tile) => {
                    const node = ko.unwrap(
                        tile.data[self.fileViewer.fileListNodeId]
                    );
                    const entry = xyEntry(node);
                    if (ko.unwrap(entry?.renderer) !== self.renderer)
                        return null;
                    const configId = ko.unwrap(entry.rendererConfig);
                    const cfg = configs.find(
                        (c) => c.configid === configId
                    );
                    const overrides = parseOverrides(ko.unwrap(entry.parsingOverrides));
                    return {
                        name: ko.unwrap(entry.name) || 'Unknown',
                        hasConfig: !!configId,
                        configName: cfg?.name || null,
                        isAutoConfig:
                            ko.unwrap(entry.rendererConfigSource) === 'auto',
                        configId: configId,
                        configObj: cfg?.config || {},
                        tileid: tile.tileid,
                        tile: tile,
                        node: node,
                        entry: entry,
                        // Identity for a later write. `entry` above is a
                        // snapshot: tile.save() replaces the objects inside
                        // tile.data, so anything writing to it must re-resolve
                        // from this id first.
                        fileId: ko.unwrap(entry.file_id),
                        url: ko.unwrap(entry.url),
                        hasOverrides: Object.keys(overrides).length > 0,
                        overrides: overrides,
                    };
                })
                .filter(Boolean);
        });

        // --- Per-file overrides in Status tab ---
        this.statusSelectedFiles = ko.observableArray([]);
        this.showOverridePanel = ko.observable(false);
        this.overrideDelimiterRadio = ko.observable('config');
        this.overrideDelimiterCustom = ko.observable('');
        this.overrideHeaderRadio = ko.observable('config');
        this.overrideHeader = ko.observable('');
        this.overrideFooterRadio = ko.observable('config');
        this.overrideFooter = ko.observable('');
        this.overrideSaving = ko.observable(false);

        // Dynamic label for button + panel title
        this.overrideTargetLabel = ko.pureComputed(() => {
            const files = self.statusSelectedFiles();
            if (files.length === 0) return '';
            if (files.length === 1) return files[0].name;
            return files.length + ' files';
        });

        // Read overrides live from node data (not cached snapshot)
        // After tile.save(), koMapping.fromJS() wraps nested props as observables,
        // so we use ko.toJS() to deeply unwrap all nested observables.
        const getFileOverrides = (file) => {
            // file.entry is the entry this renderer owns, resolved by xyEntry
            // when allXyFiles was built — not necessarily node[0].
            return parseOverrides(ko.unwrap(file.entry?.parsingOverrides));
        };

        // Load radio state from a file's existing overrides
        const loadOverridesFromFile = (file) => {
            const ov = getFileOverrides(file);
            // Delimiter
            if (!ov.delimiterCharacter) {
                self.overrideDelimiterRadio('config');
                self.overrideDelimiterCustom('');
            } else if (ov.delimiterCharacter === 'auto') {
                self.overrideDelimiterRadio('auto');
                self.overrideDelimiterCustom('');
            } else if (ov.delimiterCharacter === ',') {
                self.overrideDelimiterRadio(',');
            } else if (ov.delimiterCharacter === '\t') {
                self.overrideDelimiterRadio('tab');
            } else {
                self.overrideDelimiterRadio('other');
                self.overrideDelimiterCustom(ov.delimiterCharacter);
            }
            // Header
            if (!ov.headerFixedLines) {
                self.overrideHeaderRadio('config');
                self.overrideHeader('');
            } else if (ov.headerFixedLines === 'auto') {
                self.overrideHeaderRadio('auto');
                self.overrideHeader('');
            } else {
                self.overrideHeaderRadio('fixed');
                self.overrideHeader(ov.headerFixedLines);
            }
            // Footer
            if (!ov.footerDelimiter) {
                self.overrideFooterRadio('config');
                self.overrideFooter('');
            } else if (ov.footerDelimiter === 'none') {
                self.overrideFooterRadio('none');
                self.overrideFooter('');
            } else {
                self.overrideFooterRadio('delimited');
                self.overrideFooter(ov.footerDelimiter);
            }
        };

        const resetOverrideRadios = () => {
            self.overrideDelimiterRadio('config');
            self.overrideDelimiterCustom('');
            self.overrideHeaderRadio('config');
            self.overrideHeader('');
            self.overrideFooterRadio('config');
            self.overrideFooter('');
        };

        // React to selection changes (checkbox or row click)
        this.disposables.push(this.statusSelectedFiles.subscribe((files) => {
            if (files.length === 1) {
                loadOverridesFromFile(files[0]);
            } else {
                resetOverrideRadios();
            }
        }));

        this.toggleStatusFile = (file) => {
            const idx = self.statusSelectedFiles.indexOf(file);
            if (idx > -1) {
                self.statusSelectedFiles.splice(idx, 1);
            } else {
                self.statusSelectedFiles.push(file);
            }
        };

        this.statusSelectAll = () => {
            self.statusSelectedFiles(self.allXyFiles().slice());
        };

        this.statusDeselectAll = () => {
            self.statusSelectedFiles([]);
            self.showOverridePanel(false);
        };

        this.overridePlaceholder = ko.pureComputed(() => {
            const files = self.statusSelectedFiles();
            if (files.length === 1) {
                const cfg = files[0].configObj || {};
                return {
                    delimiter: cfg.delimiterCharacter
                        ? '(' + cfg.delimiterCharacter + ')'
                        : '(auto)',
                    header: cfg.headerFixedLines
                        ? '(' + cfg.headerFixedLines + ' lines)'
                        : '(auto)',
                    footer: cfg.footerDelimiter
                        ? '(' + cfg.footerDelimiter + ')'
                        : '(none)',
                };
            }
            return { delimiter: '', header: '', footer: '' };
        });

        this.hasOverrideValues = ko.pureComputed(() => {
            return self.overrideDelimiterRadio() !== 'config' ||
                   self.overrideHeaderRadio() !== 'config' ||
                   self.overrideFooterRadio() !== 'config';
        });

        this.clearOverrides = () => {
            resetOverrideRadios();
        };

        // Build the overrides object from radio state
        const buildOverrides = () => {
            const overrides = {};
            const delRadio = self.overrideDelimiterRadio();
            if (delRadio === 'auto') {
                overrides.delimiterCharacter = 'auto';
            } else if (delRadio === ',') {
                overrides.delimiterCharacter = ',';
            } else if (delRadio === 'tab') {
                overrides.delimiterCharacter = '\t';
            } else if (delRadio === 'other' && self.overrideDelimiterCustom()) {
                overrides.delimiterCharacter = self.overrideDelimiterCustom();
            }
            // 'config' = don't override, key not set

            if (self.overrideHeaderRadio() === 'auto') {
                overrides.headerFixedLines = 'auto';
            } else if (self.overrideHeaderRadio() === 'fixed' && self.overrideHeader()) {
                overrides.headerFixedLines = self.overrideHeader();
            }
            // 'config' = don't override, key not set

            if (self.overrideFooterRadio() === 'none') {
                overrides.footerDelimiter = 'none';
            } else if (self.overrideFooterRadio() === 'delimited' && self.overrideFooter()) {
                overrides.footerDelimiter = self.overrideFooter();
            }
            // 'config' = don't override, key not set

            return Object.keys(overrides).length > 0 ? overrides : undefined;
        };

        // The entry as tile data holds it right now. Matched on file_id like
        // parse() does, because a tile can carry the archival original beside
        // the CSV.
        const liveEntry = (file) => {
            const node = ko.unwrap(
                file.tile?.data?.[self.fileViewer.fileListNodeId]
            );
            if (!node) return null;
            return (
                (file.fileId &&
                    node.find((e) => ko.unwrap(e?.file_id) === file.fileId)) ||
                xyEntry(node)
            );
        };

        this.saveOverrides = async () => {
            const files = self.statusSelectedFiles();
            if (!files.length) return;
            self.overrideSaving(true);

            const value = buildOverrides();
            const failed = [];

            for (const file of files) {
                try {
                    // Never file.entry: tile.save() runs koMapping.fromJS over
                    // tile.data, so an entry captured when allXyFiles evaluated
                    // is an orphan. Writing to it throws nothing and saves
                    // nothing — the panel then closed reporting success.
                    const entry = liveEntry(file);
                    if (!entry) {
                        failed.push(file);
                        continue;
                    }
                    if (value) {
                        entry.parsingOverrides = value;
                    } else {
                        delete entry.parsingOverrides;
                    }
                    await file.tile.save();
                } catch (e) {
                    console.error('Override save error:', file.name, e);
                    failed.push(file);
                }
            }

            self.overrideSaving(false);
            if (failed.length) {
                // Leave the failures ticked so the panel stays open on them.
                // Re-resolved against the live list because the checkbox binding
                // compares by object identity.
                self.statusSelectedFiles(
                    self.allXyFiles().filter((live) =>
                        failed.some(
                            (f) =>
                                f.tileid === live.tileid &&
                                f.fileId === live.fileId
                        )
                    )
                );
            } else {
                self.showOverridePanel(false);
                self.statusSelectedFiles([]);
            }
            self.render();
        };

        this.onConfigSaved = async () => {
            await rendererConfigRefresh();
            if (self.selectedConfig()) {
                self.selectedConfiguration = self.rendererConfigs().find(
                    (c) => c.configid === self.selectedConfig()
                );
                applyDisplayConfig();
                self.render();
            }
        };

        this.disposables.push(this.delimiterCharacter.subscribe(() => {
            try {
                if (this.delimiterCharacter().length < 2) {
                    new RegExp(`[${this.delimiterCharacter()}\\s]+`);
                } else {
                    new RegExp(`${this.delimiterCharacter()}`);
                }
                this.invalidDelimiter(false);
            } catch {
                this.invalidDelimiter(true);
            }
        }));

        this.addConfiguration = () => {
            self.showConfigAdd(true);
        };

        this.saveConfiguration = async () => {
            const newConfiguration = {
                name: self.configName(),
                headerDelimiter: self.headerDelimiter(),
                headerFixedLines: self.headerFixedLines(),
                delimiterCharacter: self.delimiterCharacter(),
                rendererId: self.renderer,
            };
            const configSaveResponse = await fetch(
                arches.urls.renderer_config,
                {
                    method: 'POST',
                    credentials: 'include',
                    body: JSON.stringify(newConfiguration),
                    headers: {
                        'X-CSRFToken': Cookies.get('csrftoken'),
                    },
                }
            );
            if (configSaveResponse.ok) {
                invalidate(self.renderer);
                rendererConfigRefresh();
            }
            self.showConfigAdd(false);
        };

        // Track computed observables for disposal
        this.disposables.push(
            this.stagedXyTileCount,
            this.batchMode,
            this.canApplyBatch,
            this.pendingBatchCount,
            this.stagedXyFiles,
            this.allXyFiles,
            this.overrideTargetLabel,
            this.overridePlaceholder,
            this.hasOverrideValues
        );

        this.dispose = () => {
            dispose(self);
        };

        this.parse = (text, series) => {
            // Read overrides from tile data (where they're actually stored),
            // same path as rendererConfigRefresh reads rendererConfig.
            let fileOverrides = {};
            const dc = self.fileViewer?.displayContent() || self.displayContent;
            if (dc?.tile) {
                const node = ko.unwrap(dc.tile.data[self.fileViewer.fileListNodeId]);
                // Overrides belong to the file on screen. A tile can hold the
                // archival original alongside the CSV, so match on file_id and
                // only fall back to the renderer-owned entry when the viewer
                // does not tell us which file it is showing.
                const displayedId = ko.unwrap(dc.file_id);
                const entry =
                    (displayedId &&
                        (node || []).find(
                            (e) => ko.unwrap(e?.file_id) === displayedId
                        )) ||
                    xyEntry(node);
                fileOverrides = parseOverrides(
                    ko.unwrap(entry?.parsingOverrides)
                );
            }
            const baseConfig = this.selectedConfiguration?.config || {};
            const effectiveConfig = expandStoredConfig({
                ...baseConfig,
                ...fileOverrides,
            });

            const validation = XyParser.validateContent(text, {
                xColumnMode: effectiveConfig.xColumnMode,
                xColumnIndex: effectiveConfig.xColumnIndex
            });
            if (!validation.valid) {
                this.invalidDelimiter(true);
                throw new Error('Validation: ' + validation.error);
            }

            try {
                // Transforms run on the parsed spectrum, never on the file. A
                // reference-normalised FORS acquisition loses its reference and
                // dark columns here, so the routing below sees only the series
                // that are actually plotted.
                const parsedData = applyTransforms(
                    XyParser.parse(text, effectiveConfig),
                    effectiveConfig
                );
                this.invalidDelimiter(false);
                const assignments = this._columnAssignments;

                if (parsedData.ys) {
                    if (assignments && assignments.length > 0) {
                        // Roles of the series that survived the chain, never of
                        // the file's columns: a reference normalisation removes
                        // series, and no arithmetic over columns recovers them.
                        const roles = seriesRoles(parsedData, effectiveConfig);
                        const leftSeries = [];
                        const rightSeries = [];
                        parsedData.ys.forEach((yArr, i) => {
                            const role = roles[i] || 'yLeft';
                            if (role === 'yRight') {
                                rightSeries.push({
                                    value: [...parsedData.x],
                                    count: yArr,
                                    name: parsedData.seriesNames[i],
                                });
                            } else if (role !== 'ignore') {
                                leftSeries.push({
                                    value: [...parsedData.x],
                                    count: yArr,
                                    name: parsedData.seriesNames[i],
                                });
                            }
                        });
                        series.multiSeries = [...leftSeries, ...rightSeries];
                        series._rightAxisStartIndex = leftSeries.length;
                        if (leftSeries.length > 0) {
                            series.value.push(...leftSeries[0].value);
                            series.count.push(...leftSeries[0].count);
                        }
                    } else {
                        series.value.push(...parsedData.x);
                        series.count.push(...parsedData.ys[0]);
                        series.multiSeries = parsedData.ys.map((yArr, i) => ({
                            value: [...parsedData.x],
                            count: yArr,
                            name: parsedData.seriesNames[i],
                        }));
                    }
                } else {
                    series.value.push(...parsedData.x);
                    series.count.push(...parsedData.y);
                }

            } catch (e) {
                this.invalidDelimiter(true);
                throw e;
            }
        };
    },
    template: afsReaderTemplate,
});