/* FreeType reference oracle.
 *
 * Loads each font file exactly the way WebKit's FreeType backend does
 * (FT_New_Memory_Face on the raw bytes), then forces the lazy parsers with
 * FT_Load_Glyph / FT_Render_Glyph and a cmap lookup. Prints one TSV line per
 * file so the results can be diffed against the console's accept/reject
 * behaviour:
 *
 *   name  open=<err>  glyphs=<n>  char=<err>  load=<err,err,...>  render=<err,...>
 *
 * Build:
 *   gcc -O1 -o ft_probe ft_probe.c $(pkg-config --cflags --libs freetype2)
 */
#include <ft2build.h>
#include FT_FREETYPE_H
#include FT_MODULE_H

#include <stdio.h>
#include <stdlib.h>

static const char *err_name(FT_Error e)
{
    static char buf[8][32];
    static int  slot;
    const char *s = FT_Error_String(e);
    if (s) return s;
    snprintf(buf[slot], sizeof buf[0], "FT_Err(%d)", e);
    return buf[slot++ & 7];
}

int main(int argc, char **argv)
{
    FT_Int major, minor, patch;
    int printed_version = 0;

    /* One library per file. Sharing a single FT_Library across many faces crashed at
       teardown even when both faces were the unmodified base font, so that was a harness
       artefact and would have polluted every result here. */
    for (int i = 1; i < argc; i++) {
        FT_Library lib;
        if (FT_Init_FreeType(&lib)) { fprintf(stderr, "FT_Init_FreeType failed\n"); return 2; }
        if (!printed_version) {
            FT_Library_Version(lib, &major, &minor, &patch);
            fprintf(stderr, "freetype %d.%d.%d\n", major, minor, patch);
            printed_version = 1;
        }
        const char *path = argv[i];
        FILE *f = fopen(path, "rb");
        if (!f) { printf("%s\topen=NOFILE\n", path); continue; }
        fseek(f, 0, SEEK_END);
        long n = ftell(f);
        fseek(f, 0, SEEK_SET);
        unsigned char *bytes = malloc((size_t)n);
        size_t got = fread(bytes, 1, (size_t)n, f);
        fclose(f);

        FT_Face face;
        FT_Error e = FT_New_Memory_Face(lib, bytes, (FT_Long)got, 0, &face);

        printf("%s\topen=%s\tglyphs=%ld", path, err_name(e), e ? -1L : face->num_glyphs);

        if (!e) {
            /* a cmap lookup is a separate parser from the glyph loader */
            FT_UInt idx = FT_Get_Char_Index(face, 'A');
            printf("\tcharA=%u", idx);

            long limit = face->num_glyphs < 8 ? face->num_glyphs : 8;
            printf("\tload=");
            for (long g = 0; g < limit; g++) {
                FT_Error le = FT_Load_Glyph(face, (FT_UInt)g, FT_LOAD_DEFAULT);
                printf("%s%s", g ? "," : "", le ? err_name(le) : "ok");
            }
            printf("\trender=");
            for (long g = 0; g < limit; g++) {
                if (FT_Load_Glyph(face, (FT_UInt)g, FT_LOAD_DEFAULT)) { printf("%s-", g ? "," : ""); continue; }
                FT_Error re = FT_Render_Glyph(face->glyph, FT_RENDER_MODE_NORMAL);
                printf("%s%s", g ? "," : "", re ? err_name(re) : "ok");
            }
            FT_Done_Face(face);
        }
        printf("\n");
        fflush(stdout);
        free(bytes);
        FT_Done_FreeType(lib);
    }
    return 0;
}
