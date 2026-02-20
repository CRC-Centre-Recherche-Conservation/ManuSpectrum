import Papa from 'papaparse';

const SUSPICIOUS_PATTERNS = [
    /^[=+\-@]\s*[A-Z]+\s*\(/i,   // Formula injection: =CMD(), +EXEC(), -SYSTEM(), @SUM()
    /<script[\s>]/i,               // Script tags
    /javascript\s*:/i,             // javascript: URIs
    /\bon\w+\s*=/i,               // Event handlers: onclick=, onerror=
    /data\s*:\s*text\/html/i       // Data URIs with HTML
];

const PREVIEW_LINES = 20;
const MIN_NUMERIC_RATIO = 0.5;

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

/**
 * Validates file content BEFORE parsing.
 * Returns { valid: boolean, error?: string, detectedDelimiter?: string }
 */
const validateContent = (text) => {
    if (!text || typeof text !== 'string') {
        return { valid: false, error: 'Empty or invalid content' };
    }

    // 1. Binary detection — scan for null bytes
    if (text.indexOf('\0') !== -1) {
        return { valid: false, error: 'Binary content detected (null bytes found)' };
    }

    // 2. Probe PapaParse — parse first lines in preview mode
    let probeResult;
    try {
        probeResult = Papa.parse(text, {
            preview: PREVIEW_LINES,
            skipEmptyLines: 'greedy',
            dynamicTyping: false
        });
    } catch {
        return { valid: false, error: 'PapaParse probe failed' };
    }

    if (probeResult.errors && probeResult.errors.length > 0) {
        const critical = probeResult.errors.filter(e =>
            e.type === 'Quotes' || e.type === 'FieldMismatch'
        );
        if (critical.length > 0) {
            return { valid: false, error: 'Parse error: ' + critical[0].message };
        }
    }

    // 3. Shape minimum — at least 2 lines and 2 columns
    const probeData = probeResult.data;
    if (probeData.length < 2) {
        return { valid: false, error: 'Insufficient data: need at least 2 rows' };
    }
    const maxCols = Math.max(...probeData.map(row => row.length));
    if (maxCols < 2) {
        return { valid: false, error: 'Insufficient data: need at least 2 columns' };
    }

    // 4. Security scan — detect suspicious patterns in cells
    for (let i = 0; i < probeData.length; i++) {
        for (let j = 0; j < probeData[i].length; j++) {
            const cell = probeData[i][j];
            if (typeof cell !== 'string') continue;
            for (const pattern of SUSPICIOUS_PATTERNS) {
                if (pattern.test(cell)) {
                    return {
                        valid: false,
                        error: 'Suspicious content detected at row ' + (i + 1) + ', col ' + (j + 1) + ': potential injection'
                    };
                }
            }
        }
    }

    // 5. Numeric verification — at least 50% of data rows must have numeric X and Y
    let numericCount = 0;
    for (let i = 0; i < probeData.length; i++) {
        const row = probeData[i];
        if (row.length >= 2 &&
            !isNaN(parseFloat(row[0])) &&
            !isNaN(parseFloat(row[1]))) {
            numericCount++;
        }
    }
    if (numericCount / probeData.length < MIN_NUMERIC_RATIO) {
        return { valid: false, error: 'Insufficient numeric data: less than 50% of rows have numeric X/Y values' };
    }

    return {
        valid: true,
        detectedDelimiter: probeResult.meta?.delimiter
    };
};

/**
 * Auto-detects where numeric data starts in a parsed rows array.
 * Returns { dataStartIndex: number, headerLine?: string[] }
 */
const detectDataStart = (rows) => {
    let dataStartIndex = 0;

    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        if (row.length >= 1 && !isNaN(parseFloat(row[0]))) {
            dataStartIndex = i;
            break;
        }
        // If we reach the end without finding numeric data, start at 0
        if (i === rows.length - 1) {
            dataStartIndex = 0;
        }
    }

    let headerLine = null;
    if (dataStartIndex > 0) {
        const candidate = rows[dataStartIndex - 1];
        if (candidate && candidate.some(cell => cell && cell.trim() !== '')) {
            headerLine = candidate;
        }
    }

    return { dataStartIndex, headerLine };
};

/**
 * Parses text content into XY data using PapaParse.
 *
 * Config priority: file overrides > shared config > auto-detect.
 * Caller is responsible for merging overrides before calling.
 *
 * @param {string} text - raw file content
 * @param {object} config - merged configuration
 * @returns {{ x: number[], y: number[] } | { x: number[], ys: number[][], seriesNames: string[] }}
 */
const parse = (text, config) => {
    let headerLine = null;
    let workingText = text;

    // Phase 1: Pre-processing — strip footer
    if (config?.footerDelimiter) {
        workingText = workingText.split(config.footerDelimiter)[0].trim();
    }

    // Handle headerDelimiter: split text before PapaParse so header region is isolated
    if (config?.headerDelimiter) {
        const parts = workingText.split(config.headerDelimiter);
        const headerPart = parts[0].trim();
        if (headerPart) {
            const headerLines = headerPart.split('\n');
            headerLine = headerLines[headerLines.length - 1];
        }
        workingText = parts[1]?.trim() || '';
    }

    // Phase 2: Parse with PapaParse
    const papaConfig = {
        skipEmptyLines: 'greedy',
        dynamicTyping: false
    };

    // If config has a single-char delimiter, use it as override
    if (config?.delimiterCharacter && config.delimiterCharacter.length === 1) {
        papaConfig.delimiter = config.delimiterCharacter;
    }
    // If no delimiter is configured, PapaParse auto-detects

    const result = Papa.parse(workingText, papaConfig);
    let rows = result.data;

    // Filter out empty rows
    rows = rows.filter(row => row.some(cell => cell && cell.trim() !== ''));

    // Phase 3: Extract data
    let dataRows;

    if (config?.headerDelimiter) {
        // headerDelimiter already handled above; all rows are data
        // Parse headerLine as array if it's a string
        if (headerLine && typeof headerLine === 'string') {
            const headerParsed = Papa.parse(headerLine, {
                delimiter: papaConfig.delimiter,
                skipEmptyLines: 'greedy'
            });
            if (headerParsed.data.length > 0) {
                headerLine = headerParsed.data[0];
            }
        }
        dataRows = rows;
    } else if (config?.headerFixedLines) {
        const skip = parseInt(config.headerFixedLines, 10);
        if (skip > 0 && skip <= rows.length) {
            headerLine = rows[skip - 1];
        }
        dataRows = rows.slice(skip);
    } else {
        // Auto-detect: find first numeric row
        const detected = detectDataStart(rows);
        headerLine = detected.headerLine;
        dataRows = rows.slice(detected.dataStartIndex);
    }

    // Filter rows that have no numeric first cell (safety)
    dataRows = dataRows.filter(row => row.length >= 1 && !isNaN(parseFloat(row[0])));

    if (dataRows.length === 0) {
        return { x: [], y: [] };
    }

    const yColumnCount = dataRows[0].length - 1;
    const transform = config?.transformation ?? 'basic';

    if (yColumnCount > 1 && transform !== 'mean') {
        // Multi-series mode
        const seriesNames = [];
        if (headerLine && Array.isArray(headerLine)) {
            const headerTokens = headerLine.filter(el => el && el.trim() !== '');
            if (headerTokens.length >= yColumnCount + 1) {
                for (let i = 1; i <= yColumnCount; i++) {
                    seriesNames.push(headerTokens[i].trim());
                }
            }
        }
        if (seriesNames.length !== yColumnCount) {
            seriesNames.length = 0;
            for (let i = 0; i < yColumnCount; i++) {
                seriesNames.push('Y' + (i + 1));
            }
        }

        const parsedMulti = { x: [], ys: [], seriesNames };
        for (let i = 0; i < yColumnCount; i++) {
            parsedMulti.ys.push([]);
        }

        dataRows.forEach(row => {
            parsedMulti.x.push(parseFloat(row[0]));
            for (let i = 0; i < yColumnCount; i++) {
                const val = i + 1 < row.length ? parseFloat(row[i + 1]) : NaN;
                parsedMulti.ys[i].push(val);
            }
        });

        return parsedMulti;
    }

    // Single Y (or mean transform)
    const parsedData = { x: [], y: [] };

    dataRows.forEach(row => {
        parsedData.x.push(parseFloat(row[0]));
        const yValues = row.slice(1).map(v => parseFloat(v)).filter(v => !isNaN(v));
        if (yValues.length > 0) {
            parsedData.y.push(runTransformation(yValues, transform));
        } else {
            parsedData.y.push(NaN);
        }
    });

    return parsedData;
};

export default {
    transformations,
    parse,
    validateContent
};
