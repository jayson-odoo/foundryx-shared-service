/**
 * Computed-field arithmetic expressions (sprint-3/01 D7) — client mirror of
 * the backend `app/form_engine/computed.py`. Own tokenizer + recursive-descent
 * parser: `+ - * /` (unicode `×`/`÷` accepted), parentheses, unary minus,
 * sibling field refs. NEVER eval/Function on tenant content (anti-SSTI house
 * line). Runtime evaluation fails closed (missing/non-numeric ref,
 * div-by-zero → null); the SERVER recomputes authoritatively on submit —
 * this mirror only drives the live in-form display.
 */

export const MAX_EXPR_LEN = 1000;
export const MAX_TOKENS = 100;

/** Aggregate functions over a repeater column (sprint-3/02 follow-up). */
export const AGGREGATE_FUNCS = ['sum', 'avg', 'count', 'min', 'max'] as const;
export type AggregateFunc = (typeof AGGREGATE_FUNCS)[number];

export class ComputedExpressionError extends Error {}

type Token =
  | { kind: 'num'; value: number }
  | { kind: 'ref'; name: string }
  | { kind: 'op'; op: '+' | '-' | '*' | '/' }
  | { kind: 'lparen' }
  | { kind: 'rparen' };

type Node =
  | { kind: 'num'; value: number }
  | { kind: 'ref'; name: string }
  | { kind: 'agg'; func: AggregateFunc; repeaterKey: string; subKey: string | null }
  | { kind: 'neg'; operand: Node }
  | { kind: 'bin'; op: '+' | '-' | '*' | '/'; left: Node; right: Node };

export interface AggregateRef {
  func: AggregateFunc;
  repeaterKey: string;
  subKey: string | null;
}

// Anchored (not sticky) — the es5 build target has no `y` flag; we slice the
// remaining input per step instead.
const TOKEN_RE =
  /^\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)|([+\-*/×÷()]))/;
const OP_ALIASES: Record<string, '+' | '-' | '*' | '/'> = {
  '+': '+',
  '-': '-',
  '*': '*',
  '/': '/',
  '×': '*',
  '÷': '/',
};

function tokenize(expr: string): Token[] {
  if (expr.length > MAX_EXPR_LEN) {
    throw new ComputedExpressionError(`Expression exceeds ${MAX_EXPR_LEN} characters.`);
  }
  const tokens: Token[] = [];
  let rest = expr;
  while (rest.length > 0) {
    const match = TOKEN_RE.exec(rest);
    if (!match) {
      // Allow trailing whitespace; anything else is an illegal character.
      if (/^\s*$/.test(rest)) break;
      throw new ComputedExpressionError(
        `Unexpected character at position ${expr.length - rest.length}.`,
      );
    }
    if (match[1] !== undefined) tokens.push({ kind: 'num', value: Number(match[1]) });
    else if (match[2] !== undefined) tokens.push({ kind: 'ref', name: match[2] });
    else if (match[3] === '(') tokens.push({ kind: 'lparen' });
    else if (match[3] === ')') tokens.push({ kind: 'rparen' });
    else tokens.push({ kind: 'op', op: OP_ALIASES[match[3]] });
    rest = rest.slice(match[0].length);
    if (tokens.length > MAX_TOKENS) {
      throw new ComputedExpressionError(`Expression exceeds ${MAX_TOKENS} tokens.`);
    }
  }
  return tokens;
}

export interface ParsedExpression {
  source: string;
  fieldRefs: ReadonlySet<string>;
  ast: Node;
}

/** Parse, raising `ComputedExpressionError` on any syntax problem. */
export function parseExpression(expr: string): ParsedExpression {
  const tokens = tokenize(expr);
  if (tokens.length === 0) throw new ComputedExpressionError('Expression is empty.');
  let index = 0;

  const peek = () => tokens[index];
  const next = () => tokens[index++];

  // expr → term (('+'|'-') term)*
  function parseSum(): Node {
    let node = parseTerm();
    while (peek()?.kind === 'op' && ((peek() as { op: string }).op === '+' || (peek() as { op: string }).op === '-')) {
      const op = (next() as { op: '+' | '-' }).op;
      node = { kind: 'bin', op, left: node, right: parseTerm() };
    }
    return node;
  }

  // term → unary (('*'|'/') unary)*
  function parseTerm(): Node {
    let node = parseUnary();
    while (peek()?.kind === 'op' && ((peek() as { op: string }).op === '*' || (peek() as { op: string }).op === '/')) {
      const op = (next() as { op: '*' | '/' }).op;
      node = { kind: 'bin', op, left: node, right: parseUnary() };
    }
    return node;
  }

  // unary → '-' unary | primary
  function parseUnary(): Node {
    const token = peek();
    if (token?.kind === 'op' && token.op === '-') {
      next();
      return { kind: 'neg', operand: parseUnary() };
    }
    return parsePrimary();
  }

  // primary → number | aggFunc '(' ref ')' | ref | '(' expr ')'
  function parsePrimary(): Node {
    const token = next();
    if (!token) throw new ComputedExpressionError('Unexpected end of expression.');
    if (token.kind === 'num') return token;
    if (token.kind === 'ref') {
      // `func(repeater.col)` = an aggregate (function name has no dot).
      if (peek()?.kind === 'lparen' && !token.name.includes('.')) {
        const func = token.name.toLowerCase();
        if (!(AGGREGATE_FUNCS as readonly string[]).includes(func)) {
          throw new ComputedExpressionError(`Unknown function "${token.name}".`);
        }
        next(); // consume '('
        const arg = next();
        if (!arg || arg.kind !== 'ref') {
          throw new ComputedExpressionError('Expected a repeater column.');
        }
        const closing = next();
        if (!closing || closing.kind !== 'rparen') {
          throw new ComputedExpressionError('Unbalanced parentheses.');
        }
        const dot = arg.name.indexOf('.');
        const repeaterKey = dot === -1 ? arg.name : arg.name.slice(0, dot);
        const subKey = dot === -1 ? null : arg.name.slice(dot + 1);
        if (func !== 'count' && subKey === null) {
          throw new ComputedExpressionError(`${func}() needs a column, e.g. ${func}(repeater.column).`);
        }
        return { kind: 'agg', func: func as AggregateFunc, repeaterKey, subKey };
      }
      return token;
    }
    if (token.kind === 'lparen') {
      const inner = parseSum();
      const closing = next();
      if (!closing || closing.kind !== 'rparen') {
        throw new ComputedExpressionError('Unbalanced parentheses.');
      }
      return inner;
    }
    throw new ComputedExpressionError('Unexpected token in expression.');
  }

  const ast = parseSum();
  if (index !== tokens.length) {
    throw new ComputedExpressionError('Unexpected trailing content in expression.');
  }

  const refs = new Set<string>();
  collectRefs(ast, refs);
  return { source: expr, fieldRefs: refs, ast };
}

function collectRefs(node: Node, refs: Set<string>): void {
  if (node.kind === 'ref') refs.add(node.name);
  else if (node.kind === 'neg') collectRefs(node.operand, refs);
  else if (node.kind === 'bin') {
    collectRefs(node.left, refs);
    collectRefs(node.right, refs);
  }
  // 'agg' refs are collected separately (collectAggs) — not scalar fields.
}

function collectAggs(node: Node, out: AggregateRef[]): void {
  if (node.kind === 'agg') out.push({ func: node.func, repeaterKey: node.repeaterKey, subKey: node.subKey });
  else if (node.kind === 'neg') collectAggs(node.operand, out);
  else if (node.kind === 'bin') {
    collectAggs(node.left, out);
    collectAggs(node.right, out);
  }
}

/** Referenced SCALAR field keys, or null when the expression doesn't parse. */
export function fieldRefs(expr: string): Set<string> | null {
  try {
    return new Set(parseExpression(expr).fieldRefs);
  } catch {
    return null;
  }
}

/** Aggregate-over-repeater refs, or null when the expression doesn't parse. */
export function aggregateRefs(expr: string): AggregateRef[] | null {
  try {
    const out: AggregateRef[] = [];
    collectAggs(parseExpression(expr).ast, out);
    return out;
  } catch {
    return null;
  }
}

/** Evaluate, fail-closed: missing/non-numeric ref or div-by-zero → null. */
export function evaluateExpression(
  expr: string | ParsedExpression,
  values: Record<string, unknown>,
): number | null {
  let parsed: ParsedExpression;
  try {
    parsed = typeof expr === 'string' ? parseExpression(expr) : expr;
  } catch {
    return null;
  }
  return evalNode(parsed.ast, values);
}

function evalNode(node: Node, values: Record<string, unknown>): number | null {
  switch (node.kind) {
    case 'num':
      return node.value;
    case 'ref': {
      const raw = values[node.name];
      if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
      if (typeof raw === 'string' && raw.trim() !== '') {
        const n = Number(raw);
        return Number.isFinite(n) ? n : null;
      }
      return null;
    }
    case 'agg': {
      const rows = values[node.repeaterKey];
      const list = Array.isArray(rows) ? rows : [];
      if (node.func === 'count') return list.length;
      const nums: number[] = [];
      for (const row of list) {
        if (row && typeof row === 'object') {
          const cell = (row as Record<string, unknown>)[node.subKey as string];
          const n = typeof cell === 'number' ? cell : typeof cell === 'string' && cell.trim() !== '' ? Number(cell) : NaN;
          if (Number.isFinite(n)) nums.push(n);
        }
      }
      if (node.func === 'sum') return nums.reduce((a, b) => a + b, 0);
      if (nums.length === 0) return null;
      if (node.func === 'avg') return nums.reduce((a, b) => a + b, 0) / nums.length;
      if (node.func === 'min') return Math.min(...nums);
      if (node.func === 'max') return Math.max(...nums);
      return null;
    }
    case 'neg': {
      const operand = evalNode(node.operand, values);
      return operand === null ? null : -operand;
    }
    case 'bin': {
      const left = evalNode(node.left, values);
      const right = evalNode(node.right, values);
      if (left === null || right === null) return null;
      switch (node.op) {
        case '+':
          return left + right;
        case '-':
          return left - right;
        case '*':
          return left * right;
        case '/':
          return right === 0 ? null : left / right;
      }
    }
  }
}
