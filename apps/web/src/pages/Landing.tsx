import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Mail,
  Sparkles,
  CheckCircle2,
  ShieldCheck,
  Globe2,
  Languages,
  Workflow,
  FileSearch,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/AuthContext";

/**
 * Landing pública. Si el user ya está logueado lo mandamos a /inbox.
 */
export function Landing() {
  const { session, tenant, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading) return;
    if (session && tenant) navigate("/inbox", { replace: true });
    else if (session && !tenant) navigate("/onboarding", { replace: true });
  }, [session, tenant, loading, navigate]);

  return (
    <div className="min-h-screen bg-white text-zinc-900">
      {/* Header */}
      <header className="border-b bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            Order Flow
          </Link>
          <nav className="flex items-center gap-2">
            <Link
              to="/sign-in"
              className="px-3 py-1.5 text-sm text-zinc-700 hover:text-zinc-900"
            >
              Iniciar sesión
            </Link>
            <Link to="/sign-up">
              <Button size="sm">
                Crear cuenta
                <ArrowRight className="h-3.5 w-3.5 ml-1.5" />
              </Button>
            </Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="px-6 py-20 lg:py-28 max-w-6xl mx-auto text-center">
        <div className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 border border-violet-200 text-violet-900 text-xs px-3 py-1 mb-6">
          <Sparkles className="h-3 w-3" />
          Para PYMEs industriales que usan Sage 200
        </div>
        <h1 className="text-4xl lg:text-6xl font-bold tracking-tight max-w-3xl mx-auto leading-tight">
          Pedidos de tus clientes en Sage 200,{" "}
          <span className="text-violet-600">sin copiar a mano</span>.
        </h1>
        <p className="mt-6 text-lg lg:text-xl text-zinc-600 max-w-2xl mx-auto">
          Order Flow lee los pedidos PDF que llegan a tu correo, extrae los datos,
          los valida contra tu catálogo y te los deja listos para aprobar — en
          segundos en vez de horas.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link to="/sign-up">
            <Button size="lg">
              Empezar gratis
              <ArrowRight className="h-4 w-4 ml-2" />
            </Button>
          </Link>
          <Link to="/sign-in">
            <Button size="lg" variant="outline">
              Iniciar sesión
            </Button>
          </Link>
        </div>
        <p className="mt-4 text-xs text-zinc-500">
          Sin tarjeta de crédito · Configura en 5 minutos
        </p>
      </section>

      {/* Cómo funciona */}
      <section className="px-6 py-20 bg-zinc-50 border-y">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold tracking-tight">Cómo funciona</h2>
            <p className="mt-3 text-zinc-600">Tres pasos. Cero copy-paste.</p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <Step
              n={1}
              icon={Mail}
              title="Conecta tu Outlook"
              text="Order Flow vigila la carpeta donde te llegan los pedidos. Cada PDF nuevo entra al pipeline automáticamente."
            />
            <Step
              n={2}
              icon={FileSearch}
              title="La IA lee el pedido"
              text="OCR + Claude extraen cliente, líneas, precios y referencias. Multi-idioma. Reconoce las etiquetas que TÚ enseñas."
            />
            <Step
              n={3}
              icon={CheckCircle2}
              title="Apruebas y se va"
              text="Revisas, validas contra tu catálogo y precios mínimos, y un click manda el pedido a Sage 200."
            />
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="px-6 py-20 max-w-6xl mx-auto">
        <div className="text-center mb-14">
          <h2 className="text-3xl font-bold tracking-tight">
            Diseñado para tu realidad
          </h2>
          <p className="mt-3 text-zinc-600">
            Cada cliente escribe los pedidos a su manera. Order Flow se adapta.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Feature
            icon={Languages}
            title="Multi-idioma sin esfuerzo"
            text="Pedidos en francés, inglés, alemán, italiano. Enseñas qué etiqueta usa cada cliente para 'dirección de entrega' o 'transporte' una vez, y el sistema lo recuerda para siempre."
          />
          <Feature
            icon={ShieldCheck}
            title="Validación contra tu catálogo"
            text="Si una línea va por debajo del precio mínimo, Order Flow bloquea la aprobación hasta que tomes la decisión. Sin sorpresas en margen."
          />
          <Feature
            icon={Workflow}
            title="Reglas a tu medida"
            text="¿Pedido de menos de 2.500€ sin transporte? Bloquéalo. ¿Cliente con riesgo de impago? Aviso. Tú defines las reglas, Order Flow las aplica."
          />
          <Feature
            icon={Globe2}
            title="Pedido ↔ oferta automático"
            text="Cuando llega el pedido, Order Flow busca la oferta que enviaste y te muestra las diferencias en precio o cantidad — antes de que se cuelen al ERP."
          />
        </div>
      </section>

      {/* CTA final */}
      <section className="px-6 py-20 bg-gradient-to-br from-violet-600 to-indigo-700 text-white text-center">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-3xl lg:text-4xl font-bold tracking-tight">
            Empieza con tu primer cliente hoy
          </h2>
          <p className="mt-4 text-violet-100 text-lg">
            5 minutos para conectar Outlook y subir tu catálogo. El primer pedido
            llega procesado en menos de un minuto.
          </p>
          <div className="mt-8">
            <Link to="/sign-up">
              <Button size="lg" variant="outline" className="bg-white text-violet-700 hover:bg-violet-50 border-white">
                Crear mi cuenta
                <ArrowRight className="h-4 w-4 ml-2" />
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 py-10 border-t text-sm text-zinc-500 text-center">
        <p>
          Order Flow · Hecho en España · Especializado en Sage 200
        </p>
        <p className="mt-1 text-xs">
          MVP · v0.0.2 · Para soporte:{" "}
          <a href="mailto:soporte@orderflow.app" className="underline">
            soporte@orderflow.app
          </a>
        </p>
      </footer>
    </div>
  );
}

function Step({
  n,
  icon: Icon,
  title,
  text,
}: {
  n: number;
  icon: typeof Mail;
  title: string;
  text: string;
}) {
  return (
    <div className="rounded-lg bg-white border p-6 shadow-sm">
      <div className="flex items-center gap-3 mb-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-full bg-violet-100 text-violet-700 font-semibold text-sm">
          {n}
        </div>
        <Icon className="h-5 w-5 text-violet-600" />
      </div>
      <h3 className="font-semibold text-lg">{title}</h3>
      <p className="mt-2 text-sm text-zinc-600 leading-relaxed">{text}</p>
    </div>
  );
}

function Feature({
  icon: Icon,
  title,
  text,
}: {
  icon: typeof Mail;
  title: string;
  text: string;
}) {
  return (
    <div className="rounded-lg border p-6">
      <div className="flex items-center gap-3 mb-2">
        <Icon className="h-5 w-5 text-violet-600" />
        <h3 className="font-semibold text-lg">{title}</h3>
      </div>
      <p className="text-sm text-zinc-600 leading-relaxed">{text}</p>
    </div>
  );
}
