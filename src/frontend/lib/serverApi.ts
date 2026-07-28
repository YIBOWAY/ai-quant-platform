import { cache } from "react";
import { getHealth, getSettings } from "@/lib/api";

export const getCachedHealth = cache(getHealth);
export const getCachedSettings = cache(getSettings);
