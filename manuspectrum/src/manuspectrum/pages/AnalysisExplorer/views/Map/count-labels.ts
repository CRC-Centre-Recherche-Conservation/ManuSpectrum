/**
 * The document and Component counts of a map row, short for the eye
 * (« 87 docs · 103 Comp. ») and in words for a title or an accessible name
 * (« 87 documents, 103 Components »). Every call is a literal `$gettext` /
 * `$ngettext` so extraction sees each string.
 */
type Gettext = (msgid: string) => string;
type Ngettext = (singular: string, plural: string, n: number) => string;
type Interpolate = (
    message: string,
    values: Record<string, string | number>,
    disableEscaping?: boolean,
) => string;

export interface CountWords {
    $gettext: Gettext;
    $ngettext: Ngettext;
    interpolate: Interpolate;
}

/** « 87 docs · 103 Comp. », « 1 doc · 1 Comp. ». */
export function countsText(
    words: CountWords,
    documents: number,
    components: number,
): string {
    const { $gettext, $ngettext, interpolate } = words;
    return interpolate(
        $gettext("%{documents} · %{components}"),
        {
            documents: interpolate(
                $ngettext("%{n} doc", "%{n} docs", documents),
                { n: documents },
                true,
            ),
            components: interpolate(
                $ngettext("%{n} Comp.", "%{n} Comp.", components),
                { n: components },
                true,
            ),
        },
        true,
    );
}

/** « 87 documents, 103 Components », « 1 document, 1 Component ». */
export function countsName(
    words: CountWords,
    documents: number,
    components: number,
): string {
    const { $gettext, $ngettext, interpolate } = words;
    return interpolate(
        $gettext("%{documents}, %{components}"),
        {
            documents: interpolate(
                $ngettext("%{n} document", "%{n} documents", documents),
                { n: documents },
                true,
            ),
            components: interpolate(
                $ngettext("%{n} Component", "%{n} Components", components),
                { n: components },
                true,
            ),
        },
        true,
    );
}
