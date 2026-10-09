const SEGMENT_SEPARATOR = " — ";

/**
 * The first segment of an analysis name, the one that identifies the
 * record (segments are separated by a spaced dash): a gallery tab or a pane
 * pill cannot carry the whole name, which stays in its `title`. A name with
 * no separator, or an empty first segment, is returned whole.
 */
export function shortAnalysisName(name: string): string {
    const first = name.split(SEGMENT_SEPARATOR)[0].trim();
    return first || name;
}
