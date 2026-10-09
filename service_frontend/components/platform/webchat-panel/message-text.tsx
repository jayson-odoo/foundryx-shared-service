import { linkifySegments } from '@/lib/linkify';

export interface MessageTextProps {
  text: string;
}

/**
 * Renders visitor- AND agent-authored text as TEXT NODES ONLY (AC-WEB-48,
 * D-A7B-26 - the house anti-SSTI line on the client): no
 * `dangerouslySetInnerHTML`, no markdown-to-HTML, and a URL only becomes an
 * `<a href>` after `linkifySegments` has scheme-validated it. Every other
 * character - including a literal `<script>` or `javascript:` payload - is
 * plain JSX text content, which React escapes on render.
 */
export function MessageText({ text }: MessageTextProps) {
  const segments = linkifySegments(text);
  return (
    <p className="whitespace-pre-wrap break-words">
      {segments.map((segment, index) =>
        segment.type === 'link' ? (
          <a
            key={index}
            href={segment.href}
            target="_blank"
            rel="noreferrer noopener"
            className="underline underline-offset-2"
          >
            {segment.value}
          </a>
        ) : (
          <span key={index}>{segment.value}</span>
        ),
      )}
    </p>
  );
}
