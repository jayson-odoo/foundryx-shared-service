/** Route helpers for the respond.io migration tool (plan 33, roadmap A6) -
 *  single source of truth for its URLs. */

export const migrationListPath = '/omnichannel/settings/migration';
export const migrationNewPath = `${migrationListPath}/new`;
export const migrationJobPath = (jobId: string) => `${migrationListPath}/${jobId}`;
