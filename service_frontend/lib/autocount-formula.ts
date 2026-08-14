/**
 * Safe transform-formula engine (slice 16) - client mirror of the authoritative
 * backend `modules/autocount/formula.py`.
 *
 *   !!  NO eval / Function / new Function / template engine - a hand-written
 *       tokenizer + recursive-descent parser + evaluator ONLY.  !!
 *
 * An operator authors a transform as an EXPRESSION over a single input `value`
 * (the raw AutoCount source value). This drives the builder's LIVE preview; the
 * real sync runs the Python evaluator. A shared golden matrix
 * (`modules/autocount/formula_parity.json`) is asserted by BOTH vitest and
 * pytest so the two evaluators cannot silently drift (AC-16-01). Keep every
 * rule in this file identical to its Python twin.
 *
 * Grammar (EBNF)
 *   expr       = or
 *   or         = and  ( "or"  and )*
 *   and        = notx ( "and" notx )*
 *   notx       = "not" notx | comparison
 *   comparison = concat ( ("=="|"!="|"<"|"<="|">"|">=") concat )?
 *   concat     = add ( "&" add )*
 *   add        = mul ( ("+"|"-") mul )*
 *   mul        = unary ( ("*"|"/") unary )*
 *   unary      = "-" unary | call
 *   call       = primary | IDENT "(" args? ")"
 *   primary    = NUMBER | STRING | "true" | "false" | "null" | "value" | "(" expr ")"
 *
 * Fail closed: a parse fault (unknown name/function, bad arity, syntax) throws
 * `FormulaParseError` (the save gate); an evaluate fault (`number("abc")`,
 * div-by-zero, a type mismatch) throws `FormulaRuntimeError` - never a silent
 * value.
 */

// ── hard caps (mirror formula.py) ────────────────────────────────────────────
export const MAX_FORMULA_LEN = 1000;
export const MAX_TOKENS = 200;
export const MAX_DEPTH = 5; // = app/services/filter_translator.MAX_GROUP_DEPTH

// ── errors ───────────────────────────────────────────────────────────────────
export class FormulaError extends Error {}
export class FormulaParseError extends FormulaError {}
export class FormulaRuntimeError extends FormulaError {}

// ── date-token vocabulary (AC-16-14) ─────────────────────────────────────────
export interface DateTokenDef {
  token: string;
  width: number;
  field: DateField;
  description: string;
}
type DateField = 'year' | 'month' | 'day' | 'hour' | 'minute' | 'second';

export const DATE_TOKENS: readonly DateTokenDef[] = [
  { token: 'yyyy', width: 4, field: 'year', description: '4-digit year' },
  { token: 'MM', width: 2, field: 'month', description: '2-digit month (01-12)' },
  { token: 'dd', width: 2, field: 'day', description: '2-digit day (01-31)' },
  { token: 'HH', width: 2, field: 'hour', description: '2-digit hour (00-23)' },
  { token: 'mm', width: 2, field: 'minute', description: '2-digit minute (00-59)' },
  { token: 'ss', width: 2, field: 'second', description: '2-digit second (00-59)' },
];
const DATE_TOKEN_ORDER = ['yyyy', 'MM', 'dd', 'HH', 'mm', 'ss'] as const;
const DATE_TOKEN_WIDTH: Record<string, number> = Object.fromEntries(
  DATE_TOKENS.map((t) => [t.token, t.width]),
);
const DATE_TOKEN_FIELD: Record<string, DateField> = Object.fromEntries(
  DATE_TOKENS.map((t) => [t.token, t.field]),
);

export const ISO_OUTPUT_FORMAT = 'yyyy-MM-ddTHH:mm:ssZ';
export const DATE_INPUT_FORMATS: readonly string[] = [
  'yyyy/MM/dd HH:mm:ss',
  'yyyy/MM/dd',
  'yyyy-MM-dd HH:mm:ss',
  'yyyy-MM-dd',
  'dd/MM/yyyy',
  'dd/MM/yyyy HH:mm:ss',
];
export const DATE_OUTPUT_FORMATS: readonly string[] = [
  ISO_OUTPUT_FORMAT,
  'yyyy-MM-dd',
  'yyyy/MM/dd',
  'dd/MM/yyyy',
  'yyyy-MM-dd HH:mm:ss',
];

/** A parsed date as calendar components, treated as aware-UTC wall clock. */
export class FormulaDate {
  constructor(
    readonly year: number,
    readonly month: number,
    readonly day: number,
    readonly hour = 0,
    readonly minute = 0,
    readonly second = 0,
  ) {}
  iso(): string {
    const p = (n: number, w: number) => String(n).padStart(w, '0');
    return `${p(this.year, 4)}-${p(this.month, 2)}-${p(this.day, 2)}T${p(
      this.hour,
      2,
    )}:${p(this.minute, 2)}:${p(this.second, 2)}Z`;
  }
}

export type FormulaValue = null | boolean | number | string | FormulaDate;

// ── tokeniser ─────────────────────────────────────────────────────────────────
type TokenKind = 'NUMBER' | 'STRING' | 'IDENT' | 'OP' | '(' | ')' | ',' | 'EOF';
interface Token {
  kind: TokenKind;
  value: string;
}

// Multi-char operators FIRST so `==` never splits into two `=`.
const OPERATORS = ['==', '!=', '<=', '>=', '<', '>', '&', '+', '-', '*', '/'];
const STRING_ESCAPES: Record<string, string> = {
  '\\': '\\',
  '"': '"',
  "'": "'",
  n: '\n',
  t: '\t',
};
const NUMBER_RE = /^[0-9]+(?:\.[0-9]+)?/;
const IDENT_RE = /^[A-Za-z_][A-Za-z0-9_]*/;

function tokenize(source: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const n = source.length;
  while (i < n) {
    const ch = source[i];
    if (/\s/.test(ch)) {
      i += 1;
      continue;
    }
    if (ch === '(') {
      tokens.push({ kind: '(', value: ch });
      i += 1;
      continue;
    }
    if (ch === ')') {
      tokens.push({ kind: ')', value: ch });
      i += 1;
      continue;
    }
    if (ch === ',') {
      tokens.push({ kind: ',', value: ch });
      i += 1;
      continue;
    }
    if (ch === '"' || ch === "'") {
      const [str, next] = scanString(source, i);
      tokens.push({ kind: 'STRING', value: str });
      i = next;
      continue;
    }
    let matchedOp: string | null = null;
    for (const op of OPERATORS) {
      if (source.startsWith(op, i)) {
        matchedOp = op;
        break;
      }
    }
    if (matchedOp !== null) {
      tokens.push({ kind: 'OP', value: matchedOp });
      i += matchedOp.length;
      continue;
    }
    if (ch === '=') {
      throw new FormulaParseError("Use '==' for equality, not a single '='.");
    }
    const numRest = source.slice(i);
    const numM = NUMBER_RE.exec(numRest);
    if (numM) {
      tokens.push({ kind: 'NUMBER', value: numM[0] });
      i += numM[0].length;
      continue;
    }
    const identM = IDENT_RE.exec(numRest);
    if (identM) {
      tokens.push({ kind: 'IDENT', value: identM[0] });
      i += identM[0].length;
      continue;
    }
    throw new FormulaParseError(`Unexpected character '${ch}' in the formula.`);
  }
  if (tokens.length > MAX_TOKENS) {
    throw new FormulaParseError(`The formula exceeds the ${MAX_TOKENS}-token limit.`);
  }
  tokens.push({ kind: 'EOF', value: '' });
  return tokens;
}

function scanString(source: string, start: number): [string, number] {
  const quote = source[start];
  const out: string[] = [];
  let i = start + 1;
  const n = source.length;
  while (i < n) {
    const ch = source[i];
    if (ch === '\\') {
      if (i + 1 >= n) throw new FormulaParseError("The formula ends with a dangling '\\'.");
      const esc = source[i + 1];
      if (!(esc in STRING_ESCAPES)) {
        throw new FormulaParseError(`Unknown escape '\\${esc}' in a string.`);
      }
      out.push(STRING_ESCAPES[esc]);
      i += 2;
      continue;
    }
    if (ch === quote) return [out.join(''), i + 1];
    out.push(ch);
    i += 1;
  }
  throw new FormulaParseError('A string literal is missing its closing quote.');
}

// ── AST ───────────────────────────────────────────────────────────────────────
type Node =
  | { kind: 'lit'; value: FormulaValue }
  | { kind: 'value' }
  | { kind: 'unary'; op: '-' | 'not'; operand: Node }
  | { kind: 'binary'; op: string; left: Node; right: Node }
  | { kind: 'call'; name: string; args: Node[] };

// ── function catalogue (mirror of formula.py, byte-for-byte) ──────────────────
export interface FunctionArgDef {
  name: string;
  description: string;
}
export interface FunctionDef {
  name: string;
  category: 'String' | 'Number' | 'Boolean' | 'Date' | 'Logical';
  signature: string;
  args: FunctionArgDef[];
  description: string;
  example: string;
  minArgs: number;
  maxArgs: number | null; // null = variadic
}

export const FUNCTION_CATALOG: readonly FunctionDef[] = [
  {
    name: 'upper', category: 'String', signature: 'upper(text)',
    args: [{ name: 'text', description: 'the text to convert' }],
    description: 'Uppercases the text.', example: 'upper(value) → "ABC"', minArgs: 1, maxArgs: 1,
  },
  {
    name: 'lower', category: 'String', signature: 'lower(text)',
    args: [{ name: 'text', description: 'the text to convert' }],
    description: 'Lowercases the text.', example: 'lower(value) → "abc"', minArgs: 1, maxArgs: 1,
  },
  {
    name: 'trim', category: 'String', signature: 'trim(text)',
    args: [{ name: 'text', description: 'the text to trim' }],
    description: 'Removes leading and trailing whitespace.', example: 'trim(value) → "abc"', minArgs: 1, maxArgs: 1,
  },
  {
    name: 'contains', category: 'String', signature: 'contains(text, sub)',
    args: [
      { name: 'text', description: 'the text to search in' },
      { name: 'sub', description: 'the substring to look for' },
    ],
    description: 'True when text contains sub.', example: 'contains(value, "-A") → true', minArgs: 2, maxArgs: 2,
  },
  {
    name: 'replace', category: 'String', signature: 'replace(text, search, replacement)',
    args: [
      { name: 'text', description: 'the text to edit' },
      { name: 'search', description: 'the substring to replace' },
      { name: 'replacement', description: 'what to put in its place' },
    ],
    description: 'Replaces every occurrence of search with replacement.',
    example: 'replace(value, "-", "/") → "300/A001"', minArgs: 3, maxArgs: 3,
  },
  {
    name: 'concat', category: 'String', signature: 'concat(a, b, ...)',
    args: [{ name: '...', description: 'two or more values to join as text' }],
    description: 'Joins its arguments into one string.',
    example: 'concat("AC-", value) → "AC-300"', minArgs: 1, maxArgs: null,
  },
  {
    name: 'number', category: 'Number', signature: 'number(x)',
    args: [{ name: 'x', description: 'a numeric value or numeric string' }],
    description: 'Converts a numeric string to a number (fails if not numeric).',
    example: 'number("30000.0") → 30000', minArgs: 1, maxArgs: 1,
  },
  {
    name: 'round', category: 'Number', signature: 'round(x, digits)',
    args: [
      { name: 'x', description: 'the number to round' },
      { name: 'digits', description: 'how many decimal places (0 = whole number)' },
    ],
    description: 'Rounds x to the given number of decimal places (half away from zero).',
    example: 'round(number(value), 0) → 30000', minArgs: 2, maxArgs: 2,
  },
  {
    name: 'abs', category: 'Number', signature: 'abs(x)',
    args: [{ name: 'x', description: 'the number' }],
    description: 'The absolute value of x.', example: 'abs(-5) → 5', minArgs: 1, maxArgs: 1,
  },
  {
    name: 'bool', category: 'Boolean', signature: 'bool(x)',
    args: [{ name: 'x', description: "a value like 'T'/'F', 1/0, true/false" }],
    description: 'Converts a truthy/falsey token to a real boolean.',
    example: 'bool(value) → true', minArgs: 1, maxArgs: 1,
  },
  {
    name: 'parseDate', category: 'Date', signature: 'parseDate(text, inputFormat)',
    args: [
      { name: 'text', description: 'the date text AutoCount sends' },
      { name: 'inputFormat', description: 'a token format like yyyy/MM/dd HH:mm:ss' },
    ],
    description: 'Reads a date from text using the input format tokens.',
    example: 'parseDate(value, "yyyy/MM/dd HH:mm:ss")', minArgs: 2, maxArgs: 2,
  },
  {
    name: 'formatDate', category: 'Date', signature: 'formatDate(date, outputFormat)',
    args: [
      { name: 'date', description: 'a value from parseDate' },
      { name: 'outputFormat', description: 'a token format like yyyy-MM-ddTHH:mm:ssZ' },
    ],
    description: 'Writes a parsed date out using the output format tokens.',
    example: 'formatDate(parseDate(value, "yyyy/MM/dd"), "yyyy-MM-ddTHH:mm:ssZ")', minArgs: 2, maxArgs: 2,
  },
  {
    name: 'if', category: 'Logical', signature: 'if(condition, then, else)',
    args: [
      { name: 'condition', description: 'a true/false test' },
      { name: 'then', description: 'the result when the condition is true' },
      { name: 'else', description: 'the result when the condition is false' },
    ],
    description: 'Returns then when condition is true, otherwise else.',
    example: 'if(value == "T", true, false)', minArgs: 3, maxArgs: 3,
  },
  {
    name: 'default', category: 'Logical', signature: 'default(x, fallback)',
    args: [
      { name: 'x', description: 'the value to check' },
      { name: 'fallback', description: 'used when x is null' },
    ],
    description: 'Returns x, or fallback when x is null.',
    example: 'default(value, "N/A")', minArgs: 2, maxArgs: 2,
  },
];

const FUNCTION_BY_NAME: Record<string, FunctionDef> = Object.fromEntries(
  FUNCTION_CATALOG.map((f) => [f.name, f]),
);

export interface OperatorDef {
  symbol: string;
  category: 'Comparison' | 'Logical' | 'Arithmetic' | 'Text';
  description: string;
}
export const OPERATOR_CATALOG: readonly OperatorDef[] = [
  { symbol: '==', category: 'Comparison', description: 'equal to' },
  { symbol: '!=', category: 'Comparison', description: 'not equal to' },
  { symbol: '<', category: 'Comparison', description: 'less than' },
  { symbol: '<=', category: 'Comparison', description: 'less than or equal' },
  { symbol: '>', category: 'Comparison', description: 'greater than' },
  { symbol: '>=', category: 'Comparison', description: 'greater than or equal' },
  { symbol: 'and', category: 'Logical', description: 'both must be true' },
  { symbol: 'or', category: 'Logical', description: 'either may be true' },
  { symbol: 'not', category: 'Logical', description: 'negates a boolean' },
  { symbol: '+', category: 'Arithmetic', description: 'add' },
  { symbol: '-', category: 'Arithmetic', description: 'subtract' },
  { symbol: '*', category: 'Arithmetic', description: 'multiply' },
  { symbol: '/', category: 'Arithmetic', description: 'divide' },
  { symbol: '&', category: 'Text', description: 'join as text' },
];

export interface PresetDef {
  key: string;
  label: string;
  formula: string;
}
export const PRESETS: readonly PresetDef[] = [
  { key: 'text', label: 'Text', formula: 'value' },
  { key: 'boolean', label: 'Boolean', formula: 'if(value == "T", true, false)' },
  { key: 'decimal', label: 'Decimal', formula: 'number(value)' },
  { key: 'integer', label: 'Integer', formula: 'round(number(value), 0)' },
  {
    key: 'date',
    label: 'Date',
    formula: 'formatDate(parseDate(value, "yyyy/MM/dd HH:mm:ss"), "yyyy-MM-ddTHH:mm:ssZ")',
  },
  { key: 'custom', label: 'Custom', formula: '' },
];

/** Named transform → its preset equivalent, so an existing formula-NULL row can
 * show a preset in the editor without a formula. */
export const TRANSFORM_PRESET: Record<string, string> = {
  string: 'text',
  t_f_bool: 'boolean',
  bool: 'boolean',
  decimal: 'decimal',
  int: 'integer',
  date: 'date',
  datetime: 'date',
  slash_datetime: 'date',
};

// ── parser ────────────────────────────────────────────────────────────────────
class Parser {
  private pos = 0;
  private depth = 0;
  constructor(private readonly tokens: Token[]) {}

  private peek(): Token {
    return this.tokens[this.pos];
  }
  private advance(): Token {
    const tok = this.tokens[this.pos];
    if (tok.kind !== 'EOF') this.pos += 1;
    return tok;
  }
  private isKeyword(word: string): boolean {
    const tok = this.peek();
    return tok.kind === 'IDENT' && tok.value === word;
  }
  private enter(): void {
    this.depth += 1;
    if (this.depth > MAX_DEPTH) {
      throw new FormulaParseError(`The formula nests deeper than the ${MAX_DEPTH}-level limit.`);
    }
  }
  private leave(): void {
    this.depth -= 1;
  }

  parse(): Node {
    const node = this.parseOr();
    if (this.peek().kind !== 'EOF') {
      throw new FormulaParseError(
        `Unexpected '${this.peek().value}': the formula has trailing content.`,
      );
    }
    return node;
  }

  private parseOr(): Node {
    let node = this.parseAnd();
    while (this.isKeyword('or')) {
      this.advance();
      node = { kind: 'binary', op: 'or', left: node, right: this.parseAnd() };
    }
    return node;
  }
  private parseAnd(): Node {
    let node = this.parseNot();
    while (this.isKeyword('and')) {
      this.advance();
      node = { kind: 'binary', op: 'and', left: node, right: this.parseNot() };
    }
    return node;
  }
  private parseNot(): Node {
    if (this.isKeyword('not')) {
      this.advance();
      return { kind: 'unary', op: 'not', operand: this.parseNot() };
    }
    return this.parseComparison();
  }
  private parseComparison(): Node {
    const node = this.parseConcat();
    const tok = this.peek();
    if (tok.kind === 'OP' && ['==', '!=', '<', '<=', '>', '>='].includes(tok.value)) {
      this.advance();
      return { kind: 'binary', op: tok.value, left: node, right: this.parseConcat() };
    }
    return node;
  }
  private parseConcat(): Node {
    let node = this.parseAdd();
    while (this.peek().kind === 'OP' && this.peek().value === '&') {
      this.advance();
      node = { kind: 'binary', op: '&', left: node, right: this.parseAdd() };
    }
    return node;
  }
  private parseAdd(): Node {
    let node = this.parseMul();
    while (this.peek().kind === 'OP' && ['+', '-'].includes(this.peek().value)) {
      const op = this.advance().value;
      node = { kind: 'binary', op, left: node, right: this.parseMul() };
    }
    return node;
  }
  private parseMul(): Node {
    let node = this.parseUnary();
    while (this.peek().kind === 'OP' && ['*', '/'].includes(this.peek().value)) {
      const op = this.advance().value;
      node = { kind: 'binary', op, left: node, right: this.parseUnary() };
    }
    return node;
  }
  private parseUnary(): Node {
    if (this.peek().kind === 'OP' && this.peek().value === '-') {
      this.advance();
      return { kind: 'unary', op: '-', operand: this.parseUnary() };
    }
    return this.parsePrimary();
  }
  private parsePrimary(): Node {
    const tok = this.peek();
    if (tok.kind === 'NUMBER') {
      this.advance();
      return { kind: 'lit', value: Number(tok.value) };
    }
    if (tok.kind === 'STRING') {
      this.advance();
      return { kind: 'lit', value: tok.value };
    }
    if (tok.kind === 'IDENT') {
      const name = tok.value;
      if (name === 'true') {
        this.advance();
        return { kind: 'lit', value: true };
      }
      if (name === 'false') {
        this.advance();
        return { kind: 'lit', value: false };
      }
      if (name === 'null') {
        this.advance();
        return { kind: 'lit', value: null };
      }
      if (name === 'value') {
        this.advance();
        return { kind: 'value' };
      }
      if (['and', 'or', 'not'].includes(name)) {
        throw new FormulaParseError(`Unexpected operator '${name}'.`);
      }
      this.advance();
      if (this.peek().kind !== '(') {
        throw new FormulaParseError(
          `Unknown name '${name}' - expected the variable 'value', a literal, or a function call.`,
        );
      }
      if (!(name in FUNCTION_BY_NAME)) {
        throw new FormulaParseError(`Unknown function '${name}'.`);
      }
      this.enter();
      this.advance(); // '('
      const args: Node[] = [];
      if (this.peek().kind !== ')') {
        args.push(this.parseOr());
        while (this.peek().kind === ',') {
          this.advance();
          args.push(this.parseOr());
        }
      }
      if (this.peek().kind !== ')') {
        throw new FormulaParseError(`${name}(...) is missing its closing parenthesis.`);
      }
      this.advance(); // ')'
      this.leave();
      checkArity(name, args.length);
      return { kind: 'call', name, args };
    }
    if (tok.kind === '(') {
      this.enter();
      this.advance();
      const node = this.parseOr();
      if (this.peek().kind !== ')') {
        throw new FormulaParseError('Unbalanced parentheses in the formula.');
      }
      this.advance();
      this.leave();
      return node;
    }
    if (tok.kind === 'EOF') throw new FormulaParseError('The formula ended unexpectedly.');
    throw new FormulaParseError(`Unexpected '${tok.value}' in the formula.`);
  }
}

function checkArity(name: string, count: number): void {
  const fn = FUNCTION_BY_NAME[name];
  if (count < fn.minArgs || (fn.maxArgs !== null && count > fn.maxArgs)) {
    let need: string;
    if (fn.maxArgs === null) need = `at least ${fn.minArgs}`;
    else if (fn.minArgs === fn.maxArgs) need = `exactly ${fn.minArgs}`;
    else need = `${fn.minArgs}-${fn.maxArgs}`;
    throw new FormulaParseError(`${name}() takes ${need} argument(s), got ${count}.`);
  }
}

export interface ParsedFormula {
  source: string;
  ast: Node;
}

/** Parse + validate; throws `FormulaParseError` on any invalid formula (the
 * client save gate, mirrors the server 422). */
export function parseFormula(formula: string): ParsedFormula {
  if (typeof formula !== 'string' || formula.trim() === '') {
    throw new FormulaParseError('The formula must not be empty.');
  }
  if (formula.length > MAX_FORMULA_LEN) {
    throw new FormulaParseError(`The formula exceeds the ${MAX_FORMULA_LEN}-character limit.`);
  }
  const tokens = tokenize(formula);
  const ast = new Parser(tokens).parse();
  return { source: formula.trim(), ast };
}

/** Parse for the side effect; returns the error message or null. */
export function validateFormula(formula: string): string | null {
  try {
    parseFormula(formula);
    return null;
  } catch (err) {
    if (err instanceof FormulaError) return err.message;
    throw err;
  }
}

// ── evaluator ─────────────────────────────────────────────────────────────────
function toFormulaValue(raw: unknown): FormulaValue {
  if (raw === null || raw === undefined) return null;
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'number') return raw;
  if (typeof raw === 'string') return raw;
  if (raw instanceof FormulaDate) return raw;
  return String(raw);
}

function isNumber(v: FormulaValue): v is number {
  return typeof v === 'number';
}

function stringify(v: FormulaValue): string {
  if (v === null) return '';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (v instanceof FormulaDate) return v.iso();
  if (typeof v === 'number') return stringifyNumber(v);
  return v;
}

function stringifyNumber(n: number): string {
  if (Number.isInteger(n) && Math.abs(n) < 1e15) return String(n);
  return String(n);
}

const NUMERIC_STRING_RE = /^[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$/;

function toNumber(v: FormulaValue, ctx = 'number'): number {
  if (typeof v === 'number') return v;
  if (typeof v === 'boolean') throw new FormulaRuntimeError(`${ctx}() cannot convert a true/false value.`);
  if (v === null) throw new FormulaRuntimeError(`${ctx}() cannot convert an empty value.`);
  if (typeof v === 'string') {
    const s = v.trim();
    if (!NUMERIC_STRING_RE.test(s)) {
      throw new FormulaRuntimeError(`${ctx}() expected a number, got "${v}".`);
    }
    return Number(s);
  }
  throw new FormulaRuntimeError(`${ctx}() expected a number.`);
}

const BOOL_TRUE = new Set(['t', 'true', 'y', 'yes', '1']);
const BOOL_FALSE = new Set(['f', 'false', 'n', 'no', '0']);

function toBool(v: FormulaValue): boolean {
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return v !== 0;
  if (typeof v === 'string') {
    const token = v.trim().toLowerCase();
    if (BOOL_TRUE.has(token)) return true;
    if (BOOL_FALSE.has(token)) return false;
    throw new FormulaRuntimeError(`bool() expected a true/false value, got "${v}".`);
  }
  throw new FormulaRuntimeError('bool() expected a true/false value, got null.');
}

function roundTo(x: number, digits: number): number {
  if (!Number.isInteger(digits) || digits < 0 || digits > 12) {
    throw new FormulaRuntimeError('round() digits must be a whole number 0-12.');
  }
  const factor = 10 ** digits;
  const sign = x >= 0 ? 1 : -1;
  return (sign * Math.floor(Math.abs(x) * factor + 0.5)) / factor;
}

// ── date tools (hand-rolled, mirror formula.py) ──────────────────────────────
function splitFormat(fmt: string): Array<{ token: string } | { literal: string }> {
  const parts: Array<{ token: string } | { literal: string }> = [];
  let i = 0;
  const n = fmt.length;
  while (i < n) {
    let matched: string | null = null;
    for (const tok of DATE_TOKEN_ORDER) {
      if (fmt.startsWith(tok, i)) {
        matched = tok;
        break;
      }
    }
    if (matched !== null) {
      parts.push({ token: matched });
      i += matched.length;
    } else {
      parts.push({ literal: fmt[i] });
      i += 1;
    }
  }
  return parts;
}

const MONTH_MAX = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function parseDateValue(text: FormulaValue, fmt: FormulaValue): FormulaDate {
  if (typeof fmt !== 'string') throw new FormulaRuntimeError('parseDate() needs a text input format.');
  const raw = stringify(text);
  const parts = splitFormat(fmt);
  const fields: Record<string, number> = { hour: 0, minute: 0, second: 0 };
  let pos = 0;
  for (const part of parts) {
    if ('literal' in part) {
      if (pos >= raw.length || raw[pos] !== part.literal) {
        throw new FormulaRuntimeError(`parseDate() could not match "${raw}" against "${fmt}".`);
      }
      pos += 1;
      continue;
    }
    const width = DATE_TOKEN_WIDTH[part.token];
    const chunk = raw.slice(pos, pos + width);
    if (chunk.length !== width || !/^[0-9]+$/.test(chunk)) {
      throw new FormulaRuntimeError(`parseDate() could not read '${part.token}' from "${raw}".`);
    }
    fields[DATE_TOKEN_FIELD[part.token]] = Number(chunk);
    pos += width;
  }
  if (pos !== raw.length) {
    throw new FormulaRuntimeError(`parseDate() found trailing characters in "${raw}" for "${fmt}".`);
  }
  if (!('year' in fields) || !('month' in fields) || !('day' in fields)) {
    throw new FormulaRuntimeError('parseDate() input format must include yyyy, MM and dd.');
  }
  validateDateFields(fields);
  return new FormulaDate(
    fields.year,
    fields.month,
    fields.day,
    fields.hour ?? 0,
    fields.minute ?? 0,
    fields.second ?? 0,
  );
}

function validateDateFields(f: Record<string, number>): void {
  const month = f.month;
  if (month < 1 || month > 12) throw new FormulaRuntimeError(`parseDate() got an invalid month ${month}.`);
  const maxDay = MONTH_MAX[month - 1];
  if (f.day < 1 || f.day > maxDay) throw new FormulaRuntimeError(`parseDate() got an invalid day ${f.day}.`);
  if (!(f.hour >= 0 && f.hour <= 23)) throw new FormulaRuntimeError('parseDate() got an invalid hour.');
  if (!(f.minute >= 0 && f.minute <= 59)) throw new FormulaRuntimeError('parseDate() got an invalid minute.');
  if (!(f.second >= 0 && f.second <= 59)) throw new FormulaRuntimeError('parseDate() got an invalid second.');
}

function formatDateValue(value: FormulaValue, fmt: FormulaValue): string {
  if (typeof fmt !== 'string') throw new FormulaRuntimeError('formatDate() needs a text output format.');
  if (!(value instanceof FormulaDate)) {
    throw new FormulaRuntimeError('formatDate() expects a date from parseDate() as its first argument.');
  }
  const p = (n: number, w: number) => String(n).padStart(w, '0');
  const fieldValue: Record<DateField, string> = {
    year: p(value.year, 4),
    month: p(value.month, 2),
    day: p(value.day, 2),
    hour: p(value.hour, 2),
    minute: p(value.minute, 2),
    second: p(value.second, 2),
  };
  const out: string[] = [];
  for (const part of splitFormat(fmt)) {
    if ('literal' in part) out.push(part.literal);
    else out.push(fieldValue[DATE_TOKEN_FIELD[part.token]]);
  }
  return out.join('');
}

// ── eager function impls ──────────────────────────────────────────────────────
const EAGER_FUNCS: Record<string, (a: FormulaValue[]) => FormulaValue> = {
  upper: (a) => stringify(a[0]).toUpperCase(),
  lower: (a) => stringify(a[0]).toLowerCase(),
  trim: (a) => stringify(a[0]).trim(),
  contains: (a) => stringify(a[0]).includes(stringify(a[1])),
  replace: (a) => stringify(a[0]).split(stringify(a[1])).join(stringify(a[2])),
  concat: (a) => a.map(stringify).join(''),
  number: (a) => toNumber(a[0]),
  round: (a) => roundTo(toNumber(a[0], 'round'), toNumber(a[1], 'round')),
  abs: (a) => Math.abs(toNumber(a[0], 'abs')),
  bool: (a) => toBool(a[0]),
  parseDate: (a) => parseDateValue(a[0], a[1]),
  formatDate: (a) => formatDateValue(a[0], a[1]),
};

function typeName(v: FormulaValue): string {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return 'boolean';
  if (typeof v === 'number') return 'number';
  if (v instanceof FormulaDate) return 'date';
  return 'text';
}

function valuesEqual(a: FormulaValue, b: FormulaValue): boolean {
  if (a === null || b === null) return a === null && b === null;
  if (typeof a === 'boolean' || typeof b === 'boolean') {
    return typeof a === 'boolean' && typeof b === 'boolean' && a === b;
  }
  if (isNumber(a) && isNumber(b)) return a === b;
  if (typeof a === 'string' && typeof b === 'string') return a === b;
  if (a instanceof FormulaDate && b instanceof FormulaDate) return a.iso() === b.iso();
  return false;
}

function compare(op: string, a: FormulaValue, b: FormulaValue): boolean {
  let left: number | string;
  let right: number | string;
  if (isNumber(a) && isNumber(b)) {
    left = a;
    right = b;
  } else if (typeof a === 'string' && typeof b === 'string') {
    left = a;
    right = b;
  } else if (a instanceof FormulaDate && b instanceof FormulaDate) {
    left = a.iso();
    right = b.iso();
  } else {
    throw new FormulaRuntimeError(`Cannot compare ${typeName(a)} and ${typeName(b)} with '${op}'.`);
  }
  if (op === '<') return left < right;
  if (op === '<=') return left <= right;
  if (op === '>') return left > right;
  return left >= right;
}

function toBoolStrict(v: FormulaValue): boolean {
  if (typeof v === 'boolean') return v;
  throw new FormulaRuntimeError(`Expected a true/false value, got ${typeName(v)}.`);
}

function evalNode(node: Node, value: FormulaValue): FormulaValue {
  switch (node.kind) {
    case 'lit':
      return node.value;
    case 'value':
      return value;
    case 'unary':
      if (node.op === 'not') return !toBoolStrict(evalNode(node.operand, value));
      return -toNumber(evalNode(node.operand, value), 'negation');
    case 'binary':
      return evalBinary(node, value);
    case 'call':
      return evalCall(node, value);
    default:
      throw new FormulaRuntimeError('Corrupt formula node.');
  }
}

function evalBinary(
  node: { op: string; left: Node; right: Node },
  value: FormulaValue,
): FormulaValue {
  const op = node.op;
  if (op === 'and') return toBoolStrict(evalNode(node.left, value)) && toBoolStrict(evalNode(node.right, value));
  if (op === 'or') return toBoolStrict(evalNode(node.left, value)) || toBoolStrict(evalNode(node.right, value));

  const left = evalNode(node.left, value);
  const right = evalNode(node.right, value);
  if (op === '==') return valuesEqual(left, right);
  if (op === '!=') return !valuesEqual(left, right);
  if (['<', '<=', '>', '>='].includes(op)) return compare(op, left, right);
  if (op === '&') return stringify(left) + stringify(right);

  const ln = toNumber(left, 'arithmetic');
  const rn = toNumber(right, 'arithmetic');
  if (op === '+') return ln + rn;
  if (op === '-') return ln - rn;
  if (op === '*') return ln * rn;
  if (op === '/') {
    if (rn === 0) throw new FormulaRuntimeError('Division by zero.');
    return ln / rn;
  }
  throw new FormulaRuntimeError(`Unknown operator '${op}'.`);
}

function evalCall(node: { name: string; args: Node[] }, value: FormulaValue): FormulaValue {
  const name = node.name;
  if (name === 'if') {
    const cond = toBoolStrict(evalNode(node.args[0], value));
    return cond ? evalNode(node.args[1], value) : evalNode(node.args[2], value);
  }
  if (name === 'default') {
    const first = evalNode(node.args[0], value);
    return first !== null ? first : evalNode(node.args[1], value);
  }
  const impl = EAGER_FUNCS[name];
  if (!impl) throw new FormulaRuntimeError(`Unknown function '${name}'.`);
  return impl(node.args.map((arg) => evalNode(arg, value)));
}

/** Evaluate `formula` with the input `value`. Throws `FormulaParseError` /
 * `FormulaRuntimeError` (fail closed). */
export function evaluateFormula(formula: string | ParsedFormula, value: unknown): FormulaValue {
  const parsed = typeof formula === 'string' ? parseFormula(formula) : formula;
  return evalNode(parsed.ast, toFormulaValue(value));
}

/** A JSON-safe projection for the wire (FormulaDate → ISO; integer number → int). */
export function resultToJson(v: FormulaValue): unknown {
  if (v instanceof FormulaDate) return v.iso();
  return v;
}

export interface FormulaTestResult {
  ok: boolean;
  output: unknown;
  error: string | null;
}

/** Live preview for the builder's Testing tab (AC-16-20): a value in → output
 * or a named error, never a blank. */
export function testFormula(formula: string, value: unknown): FormulaTestResult {
  try {
    return { ok: true, output: resultToJson(evaluateFormula(formula, value)), error: null };
  } catch (err) {
    if (err instanceof FormulaError) return { ok: false, output: null, error: err.message };
    throw err;
  }
}
