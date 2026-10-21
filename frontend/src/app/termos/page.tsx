import type { Metadata } from "next";
import { LegalPage } from "@/components/site/legal-page";

export const metadata: Metadata = { title: "Termos de uso" };

export default function TermosPage() {
  return (
    <LegalPage title="Termos de uso" updated="21 de outubro de 2026">
      <h2>1. O que é o Minuta</h2>
      <p>
        O Minuta transforma documentos que você já usa (Word ou PDF digitado) em modelos com campos variáveis e gera documentos
        preenchidos a partir de formulários, planilhas ou kits. O conteúdo dos modelos é seu: o Minuta não redige, não revisa
        juridicamente e não presta orientação jurídica.
      </p>
      <h2>2. Sua conta</h2>
      <ul>
        <li>Você é responsável pelos dados que envia e pelo uso que faz dos documentos gerados.</li>
        <li>Mantenha sua senha em sigilo. Atividades feitas com sua conta são consideradas feitas por você.</li>
        <li>É proibido usar o serviço para fraude, falsificação de documentos ou qualquer finalidade ilícita.</li>
      </ul>
      <h2>3. Inteligência artificial</h2>
      <p>
        Recursos de IA sugerem campos, preenchem formulários a partir de texto e apontam possíveis inconsistências. As sugestões
        podem conter erros: nada é aplicado sem sua confirmação, e você deve conferir o documento antes de usá-lo.
      </p>
      <h2>4. Planos, pagamento e cancelamento</h2>
      <ul>
        <li>O plano Grátis não exige cartão. Planos pagos são cobrados no cartão de crédito (mensal ou anual) ou por Pix.</li>
        <li>Você pode cancelar a qualquer momento no próprio app; o acesso continua até o fim do período já pago.</li>
        <li>Mudanças de plano são calculadas proporcionalmente ao período restante.</li>
        <li>Os limites de cada plano (documentos por mês, linhas por lote, análises com IA) estão na página de preços.</li>
      </ul>
      <h2>5. Disponibilidade</h2>
      <p>
        Trabalhamos para manter o serviço disponível, mas podem ocorrer interrupções para manutenção ou por falhas de terceiros.
        Documentos gerados ficam disponíveis para download por tempo limitado; guarde uma cópia do que precisar.
      </p>
      <h2>6. Contato</h2>
      <p>Dúvidas sobre estes termos: pelo canal de suporte indicado no app.</p>
    </LegalPage>
  );
}
