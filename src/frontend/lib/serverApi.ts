import { cache } from "react";
import {
  getEffectivePaperSafety,
  getHealth,
  getSettings,
} from "@/lib/api";

export const getCachedHealth = cache(getHealth);
export const getCachedSettings = cache(getSettings);
export const getCachedEffectivePaperSafety = cache(getEffectivePaperSafety);
