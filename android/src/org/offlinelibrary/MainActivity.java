package org.offlinelibrary;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Shows the library's index.html (and its prebuilt _search index) from a folder the user picks.
 *
 * Files are served to the WebView under a fake origin, https://library.local/..., by
 * shouldInterceptRequest(). Nothing goes over the network. Document links (PDF, EPUB, ...)
 * are handed to whatever reader app is installed.
 */
public class MainActivity extends Activity {
    private static final int REQ_PICK = 1;
    private static final String HOST = "library.local";
    private static final String BASE = "https://" + HOST + "/";
    private static final Pattern PAGE = Pattern.compile("page=(\\d+)");

    private WebView web;
    private SharedPreferences prefs;
    private Uri tree;
    /** folder path ("" = library root) -> (child name -> document id). Saves re-listing 1000+ index files. */
    private final Map<String, Map<String, String>> dirCache = new HashMap<>();

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        web.setWebViewClient(new LibraryClient());

        prefs = getSharedPreferences("library", MODE_PRIVATE);
        String saved = prefs.getString("tree", null);
        if (saved != null && stillAllowed(Uri.parse(saved))) {
            tree = Uri.parse(saved);
            if (state != null) web.restoreState(state); else openLibrary();
        } else {
            pickFolder();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    private boolean stillAllowed(Uri uri) {
        for (android.content.UriPermission p : getContentResolver().getPersistedUriPermissions()) {
            if (p.getUri().equals(uri) && p.isReadPermission()) return true;
        }
        return false;
    }

    private void pickFolder() {
        toast("Choose the library folder you extracted (the one that contains index.html)");
        startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), REQ_PICK);
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (req != REQ_PICK) return;
        if (result != RESULT_OK || data == null || data.getData() == null) {
            if (tree == null) finish();   // nothing to show without a library
            return;
        }
        Uri picked = data.getData();
        getContentResolver().takePersistableUriPermission(picked, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        tree = picked;
        prefs.edit().putString("tree", picked.toString()).apply();
        openLibrary();
    }

    private void openLibrary() {
        synchronized (dirCache) { dirCache.clear(); }
        if (resolve("index.html") == null) {
            toast("index.html was not found in that folder. Pick the folder that holds index.html and _search.");
            pickFolder();
            return;
        }
        web.clearHistory();
        web.loadUrl(BASE + "index.html");
    }

    // ---------------------------------------------------------------- folder access

    /** Turns "Basic Survival/FM 21-76.pdf" into a content:// URI inside the picked folder, or null. */
    private Uri resolve(String path) {
        if (tree == null) return null;
        String docId = DocumentsContract.getTreeDocumentId(tree);
        String dirKey = "";
        for (String part : path.split("/")) {
            if (part.isEmpty()) continue;
            String child = children(dirKey, docId).get(part);
            if (child == null) return null;
            docId = child;
            dirKey = dirKey + "/" + part;
        }
        return DocumentsContract.buildDocumentUriUsingTree(tree, docId);
    }

    private Map<String, String> children(String dirKey, String docId) {
        synchronized (dirCache) {
            Map<String, String> m = dirCache.get(dirKey);
            if (m != null) return m;
            m = new HashMap<>();
            Uri q = DocumentsContract.buildChildDocumentsUriUsingTree(tree, docId);
            String[] cols = {DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                             DocumentsContract.Document.COLUMN_DISPLAY_NAME};
            try (Cursor c = getContentResolver().query(q, cols, null, null, null)) {
                while (c != null && c.moveToNext()) m.put(c.getString(1), c.getString(0));
            } catch (Exception ignored) {
                // unreadable folder: treat as empty
            }
            dirCache.put(dirKey, m);
            return m;
        }
    }

    private static String ext(String path) {
        int dot = path.lastIndexOf('.');
        return dot < 0 ? "" : path.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    /** MIME types for the files index.html itself loads. */
    private static String webMime(String path) {
        switch (ext(path)) {
            case "html": case "htm": return "text/html";
            case "js": return "application/javascript";
            case "css": return "text/css";
            case "json": return "application/json";
            case "svg": return "image/svg+xml";
            case "png": return "image/png";
            case "jpg": case "jpeg": return "image/jpeg";
            default: return "application/octet-stream";
        }
    }

    /** MIME type to send to the reader app when a book link is tapped. */
    private static String docMime(String path) {
        switch (ext(path)) {
            case "pdf":  return "application/pdf";
            case "epub": return "application/epub+zip";
            case "docx": return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
            case "doc":  return "application/msword";
            case "txt":
            case "md":   return "text/plain";   // few apps register text/markdown
            default:     return "*/*";          // shows the "Open with…" list
        }
    }

    // ---------------------------------------------------------------- WebView wiring

    private class LibraryClient extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (!HOST.equals(u.getHost())) return null;
            String path = u.getPath() == null ? "" : u.getPath();
            Uri doc = resolve(path);
            try {
                if (doc != null) {
                    InputStream in = getContentResolver().openInputStream(doc);
                    return new WebResourceResponse(webMime(path), "utf-8", in);
                }
            } catch (Exception ignored) {
                // fall through to 404
            }
            return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found",
                    new HashMap<String, String>(), new ByteArrayInputStream(new byte[0]));
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (HOST.equals(u.getHost())) {
                String path = u.getPath() == null ? "" : u.getPath();
                if (webMime(path).equals("text/html")) return false;   // stay in the app
                openDocument(path, u.getFragment());
                return true;
            }
            try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (ActivityNotFoundException ignored) { }
            return true;
        }
    }

    private void openDocument(String path, String fragment) {
        Uri doc = resolve(path);
        if (doc == null) { toast("File not found: " + path); return; }
        Intent i = new Intent(Intent.ACTION_VIEW);
        i.setDataAndType(doc, docMime(path));
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(i);
            // Reader apps ignore "#page=N" on content:// links, so tell the user where to go.
            if (fragment != null) {
                Matcher m = PAGE.matcher(fragment);
                if (m.find()) toast("Match is on page " + m.group(1));
            }
        } catch (ActivityNotFoundException e) {
            toast("No app installed that can open ." + ext(path) + " files. Install a PDF / e-book reader.");
        }
    }

    // ---------------------------------------------------------------- menu & back

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "Change library folder");
        menu.add(0, 2, 0, "Reload");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == 1) { pickFolder(); return true; }
        if (item.getItemId() == 2) { openLibrary(); return true; }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    private void toast(String msg) {
        Toast.makeText(this, msg, Toast.LENGTH_LONG).show();
    }
}
