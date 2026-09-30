import { ExternalLink } from "lucide-react-native";
import { Linking, Pressable, Text, View } from "react-native";
import { z } from "zod";
import { Card, colors, s } from "./ui";

const itemSchema = z.object({
  title: z.string(),
  url: z.string(),
  description: z.string().optional(),
  badge: z.string().optional(),
  source: z.string().optional(),
});

function asItems(args: unknown): { title?: string; items: z.infer<typeof itemSchema>[] } {
  const parsed = z
    .object({ title: z.string().optional(), items: z.array(itemSchema) })
    .safeParse(args);
  if (parsed.success) return parsed.data;
  const arr = z.array(itemSchema).safeParse(args);
  if (arr.success) return { items: arr.data };
  return { items: [] };
}

function hostLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Generative-UI cards for agent-presented lists (stories, articles, results). */
export function StoryCards({ args, loading }: { args: unknown; loading: boolean }) {
  const { title, items } = asItems(args);
  if (!items.length && !loading) return null;
  return (
    <View style={{ gap: 8, width: "100%", maxWidth: 440 }}>
      {title ? <Text style={s.heading}>{title}</Text> : null}
      {loading && !items.length ? (
        <Card style={{ padding: 13 }}>
          <Text style={s.muted}>Gathering…</Text>
        </Card>
      ) : null}
      {items.map((item, i) => (
        <Pressable
          key={`${item.url}-${i}`}
          onPress={() => {
            void Linking.openURL(item.url);
          }}
        >
          <Card style={{ padding: 12 }}>
            <View style={[s.row, { gap: 10 }]}>
              <View style={{ flex: 1, gap: 3 }}>
                <Text style={[s.text, { fontWeight: "600" }]}>{item.title}</Text>
                {item.description ? (
                  <Text style={s.muted} numberOfLines={2}>
                    {item.description}
                  </Text>
                ) : null}
                <View style={[s.row, { gap: 6 }]}>
                  <Text style={s.small}>{item.source || hostLabel(item.url)}</Text>
                  {item.badge ? <Text style={s.small}>· {item.badge}</Text> : null}
                </View>
              </View>
              <ExternalLink size={18} color={colors.blueDark} />
            </View>
          </Card>
        </Pressable>
      ))}
    </View>
  );
}
