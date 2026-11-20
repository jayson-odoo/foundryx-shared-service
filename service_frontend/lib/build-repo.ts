/** Build repository shape (`owner/repo`), the SAME rule the backend enforces
 * (`BUILD_REPO_PATTERN` in modules/ideation/schemas.py): each segment 1 to 100 of
 * `[A-Za-z0-9_.-]`, no `.`/`..` segment, no leading `-`. */
export const BUILD_REPO_PATTERN =
  /^(?!\.{1,2}\/)(?!-)[A-Za-z0-9_.-]{1,100}\/(?!\.{1,2}$)(?!-)[A-Za-z0-9_.-]{1,100}$/;

export const BUILD_REPO_ERROR = 'Enter the build repository as owner/repo.';

export function isValidBuildRepo(value: string): boolean {
  return BUILD_REPO_PATTERN.test(value);
}
