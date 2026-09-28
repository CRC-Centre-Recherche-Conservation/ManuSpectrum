/** A chemical element's cell on the standard 18-column periodic table; rows 9 and 10 hold the lanthanides and actinides. */
export interface ElementPlace {
    symbol: string;
    row: number;
    column: number;
}

export const PERIODIC_COLUMNS = 18;

/** One line per row of the grid, one symbol or `.` per column. */
const ROWS: readonly string[] = [
    "H . . . . . . . . . . . . . . . . He",
    "Li Be . . . . . . . . . . B C N O F Ne",
    "Na Mg . . . . . . . . . . Al Si P S Cl Ar",
    "K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr",
    "Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe",
    "Cs Ba La Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn",
    "Fr Ra Ac Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og",
    ". . . . . . . . . . . . . . . . . .",
    ". . . Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu .",
    ". . . Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr .",
];

export const PERIODIC_ROWS = ROWS.length;

/** The 118 elements, row by row. */
export const PERIODIC_TABLE: readonly ElementPlace[] = ROWS.flatMap(
    (line, rowIndex) =>
        line
            .split(" ")
            .flatMap((symbol, columnIndex) =>
                symbol === "."
                    ? []
                    : [{ symbol, row: rowIndex + 1, column: columnIndex + 1 }],
            ),
);

const BY_SYMBOL = new Map(PERIODIC_TABLE.map((place) => [place.symbol, place]));

/** The cell of `symbol` (case as in the table), else null. */
export function placeOf(symbol: string): ElementPlace | null {
    return BY_SYMBOL.get(symbol) ?? null;
}
