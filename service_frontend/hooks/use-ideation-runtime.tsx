'use client';

import { createContext, useContext, type ReactNode } from 'react';
import { ideationService, type IdeaService } from '@/services/ideation-service';
import {
  ideaFormHref,
  ideaNewPath,
  ideasListPath,
} from '@/app/(protected)/ideation/ideas/components/paths';

/**
 * Ideation runtime — the "one component, two modes" seam (WS-C1 / AC-CAP-9/10).
 *
 * The operator Ideas list / triage board / detail form are a SINGLE component
 * set. Which backend + which URLs they talk to is injected here, so the SAME
 * components render on the operator pages (app JWT, `/ideation/*` routes,
 * operator URLs) AND chrome-less inside the host iframe (embed token, `/embed/*`
 * routes, embed URLs). No provider = the operator default (so the operator pages
 * are unchanged by construction — AC-CAP-14).
 */
export interface IdeaPaths {
  /** The list URL (embed mode carries the `#token=…` fragment). */
  listHref: string;
  /** The detail/form URL for an idea (optionally in edit mode). */
  formHref: (id: string, opts?: { edit?: boolean }) => string;
  /** The create URL (operator only; embed creates via the capture dialog). */
  newHref: string;
}

export interface IdeationRuntime {
  mode: 'operator' | 'embed';
  service: IdeaService;
  paths: IdeaPaths;
}

const OPERATOR_RUNTIME: IdeationRuntime = {
  mode: 'operator',
  service: ideationService,
  paths: {
    listHref: ideasListPath,
    formHref: (id, opts) => ideaFormHref(id, opts),
    newHref: ideaNewPath,
  },
};

const IdeationRuntimeContext = createContext<IdeationRuntime | null>(null);

export function IdeationRuntimeProvider({
  runtime,
  children,
}: {
  runtime: IdeationRuntime;
  children: ReactNode;
}) {
  return (
    <IdeationRuntimeContext.Provider value={runtime}>{children}</IdeationRuntimeContext.Provider>
  );
}

/** The active ideation runtime — operator default outside any provider. */
export function useIdeationRuntime(): IdeationRuntime {
  return useContext(IdeationRuntimeContext) ?? OPERATOR_RUNTIME;
}
