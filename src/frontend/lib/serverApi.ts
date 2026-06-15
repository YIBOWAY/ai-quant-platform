import { cache } from "react";
import { getHealth } from "@/lib/api";

export const getCachedHealth = cache(getHealth);
