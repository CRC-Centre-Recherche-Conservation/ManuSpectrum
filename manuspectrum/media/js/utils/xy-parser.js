const average = (yValues) => {
    return yValues.reduce((total, num) => total + num, 0) / yValues.length;
};

const runTransformation = (yValues, transform) => {
    switch (transform) {
        case 'mean':
            return average(yValues);
        default:
            return yValues[0];
    }
};

const transformations = () => {
    return ['mean'];
};

const parse = (text, config) => {
    let values;
    let headerLine = null;
    let workingText = text;

    try {
        if (config?.footerDelimiter) {
            workingText = workingText
                .split(config.footerDelimiter)[0]
                .trim();
        }

        if (config?.headerDelimiter) {
            const parts = workingText.split(config.headerDelimiter);
            const headerPart = parts[0].trim();
            if (headerPart) {
                const headerLines = headerPart.split('\n');
                headerLine = headerLines[headerLines.length - 1];
            }
            values = parts[1].trim().split('\n');
        } else if (config?.headerFixedLines) {
            const lines = workingText.split('\n');
            if (config.headerFixedLines > 0) {
                headerLine = lines[config.headerFixedLines - 1];
            }
            values = lines.slice(config.headerFixedLines);
        } else {
            values = workingText.trim().split('\n');
        }
    } catch {
        values = workingText.trim().split('\n');
    }

    // Filter out empty/blank lines
    values = values.filter(line => line.trim() !== '');

    const delimiterCharacter = config?.delimiterCharacter ?? ',';

    try {
        const valueRegex =
            delimiterCharacter.length < 2
                ? new RegExp(`[${delimiterCharacter}\\s]+`)
                : new RegExp(`${delimiterCharacter}`);

        const transform = config?.transformation ?? 'basic';

        const firstRec = values[0]?.trim().split(valueRegex).filter(el => el !== '');
        const yColumnCount = firstRec ? firstRec.length - 1 : 0;

        if (yColumnCount > 1 && transform !== 'mean') {
            const seriesNames = [];
            if (headerLine) {
                const headerTokens = headerLine
                    .trim()
                    .split(valueRegex)
                    .filter(el => el !== '');
                if (headerTokens.length >= yColumnCount + 1) {
                    for (let i = 1; i <= yColumnCount; i++) {
                        seriesNames.push(headerTokens[i]);
                    }
                }
            }
            if (seriesNames.length !== yColumnCount) {
                seriesNames.length = 0;
                for (let i = 0; i < yColumnCount; i++) {
                    seriesNames.push(`Y${i + 1}`);
                }
            }

            const parsedMulti = { x: [], ys: [], seriesNames };
            for (let i = 0; i < yColumnCount; i++) {
                parsedMulti.ys.push([]);
            }

            values.forEach(val => {
                const rec = val
                    .trim()
                    .split(valueRegex)
                    .filter(element => element !== '');

                parsedMulti.x.push(parseFloat(rec[0]));

                const yValues = rec.slice(1).map(v => parseFloat(v));
                for (let i = 0; i < yColumnCount; i++) {
                    parsedMulti.ys[i].push(
                        i < yValues.length ? yValues[i] : NaN
                    );
                }
            });

            return parsedMulti;
        }

        const parsedData = { x: [], y: [] };

        values.forEach(val => {
            const rec = val
                .trim()
                .split(valueRegex)
                .filter(element => element !== '');

            parsedData.x.push(parseFloat(rec[0]));

            const yValues = rec.slice(1).map(v => parseFloat(v));
            parsedData.y.push(runTransformation(yValues, transform));
        });

        return parsedData;
    } catch (e) {
        if (e instanceof SyntaxError) {
            throw new Error(
                'Invalid regular expression. Delimiter Character in config must be a valid regular expression.'
            );
        }
        throw e;
    }
};

export default {
    transformations,
    parse
};
