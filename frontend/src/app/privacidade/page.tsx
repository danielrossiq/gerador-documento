import type { Metadata } from "next";
import { LegalPage } from "@/components/site/legal-page";

export const metadata: Metadata = { title: "Política de privacidade" };

export default function PrivacidadePage() {
  return (
    <LegalPage title="Política de privacidade" updated="21 de outubro de 2026">
      <h2>1. Que dados tratamos</h2>
      <ul>
        <li>Dados da conta: nome, e-mail e nome do espaço de trabalho.</li>
        <li>Documentos e modelos que você envia e os valores que preenche para gerar documentos.</li>
        <li>Registros técnicos de uso e segurança (por exemplo, data de acesso e endereço IP), sem o conteúdo dos documentos.</li>
        <li>Dados de pagamento são tratados pelo processador de pagamentos; o Minuta não armazena número de cartão.</li>
      </ul>
      <h2>2. Para que usamos</h2>
      <p>Para prestar o serviço que você contratou: criar modelos, gerar documentos, manter a segurança da conta e cobrar o plano.</p>
      <h2>3. Inteligência artificial</h2>
      <p>
        Quando você usa um recurso de IA, enviamos ao provedor de IA apenas o texto necessário para aquela tarefa, com a opção que
        impede o provedor de guardar ou usar os dados para treinamento. Os recursos de IA podem ser desligados.
      </p>
      <h2>4. Por quanto tempo guardamos</h2>
      <ul>
        <li>Documentos gerados ficam disponíveis por 7 dias e depois são apagados automaticamente.</li>
        <li>Modelos, campos e valores preenchidos ficam enquanto a sua conta existir.</li>
        <li>Registros técnicos são mantidos pelo tempo necessário à segurança e a obrigações legais.</li>
      </ul>
      <h2>5. Seus direitos</h2>
      <p>
        Você pode pedir acesso, correção, exportação completa ou exclusão dos seus dados e da sua conta a qualquer momento, pelo
        canal de suporte indicado no app.
      </p>
      <h2>6. Compartilhamento</h2>
      <p>
        Não vendemos dados. Compartilhamos apenas com prestadores necessários ao serviço (hospedagem, armazenamento, envio de
        e-mail, processamento de pagamento e IA), sob obrigações de confidencialidade.
      </p>
    </LegalPage>
  );
}
