// Checks a GS1 Digital Link for the resolver with the GS1 Barcode Syntax Engine.
//   node callGS1encoder.js "https://id.gs1.org/01/09506000134352/10/ABC"   (a GS1 Digital Link URI)
//   node callGS1encoder.js "(01)09506000134352(10)ABC"                    (an element string)
// A GS1 Digital Link URI goes through the engine's own Digital Link parser, which also checks the qualifiers
// of the key, their order and that no data attribute is in the path (GS1 Digital Link URI Syntax 1.7,
// sections 4.9 and 4.10). Exit status 0 when valid, 1 (with the engine's message) when not.
import {GS1encoder} from "gs1encoder";

const gs1encoder = new GS1encoder();
await gs1encoder.init();
const input = process.argv[2] ? process.argv[2] : "(01)09521234543213(99)TESTING123";
try
{
    if (input.startsWith("https://") || input.startsWith("http://"))
        gs1encoder.dataStr = input;
    else
    {
        gs1encoder.aiDataStr = input;
        console.log("%s", gs1encoder.getDLuri(null));
    }
}
catch (e)
{
    console.log("Error: %s", e.message);
    gs1encoder.free();
    process.exit(1);
}
gs1encoder.free();
