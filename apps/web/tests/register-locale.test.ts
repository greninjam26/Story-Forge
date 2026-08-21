import { api } from "../lib/api";

type RegisterParameters = Parameters<typeof api.register>;
type LocaleIsRequired = [string, string] extends RegisterParameters
  ? false
  : true;

const localeIsRequired: LocaleIsRequired = true;
void localeIsRequired;
